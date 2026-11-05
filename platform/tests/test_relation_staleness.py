"""Effective relation status, staleness and default views (slice 3b, plan G2-C, task 4)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import pytest

from factory.events.envelope import Actor
from factory.model.lineage import DEFAULT_STATUSES, EdgeStatus, LineageDecision, RelationProposal
from factory.model.references import ReferenceResolutionDecided
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.contributions import (
    contribution_agreement,
    contribution_next,
    contribution_record,
    resolve_contribution,
)
from factory.services.extraction import ContributionBatch
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.references import extract_references
from factory.services.relations import (
    decide_relation,
    list_relations,
    propose_relation,
    relation_counts,
    relation_view,
    relation_views,
)
from tests.contribution_helpers import P2, P4, P5, item
from tests.document_helpers import StubConverter, make_registry, run_convert
from tests.lineage_helpers import (
    Lineage,
    ctr_a,
    ctr_b,
    disputed,
    lin,
    record_both,
    screened,
    world,
)


def _propose(project: Project, agent: Actor, lin: Lineage, target: str, basis: str | None) -> str:
    p = RelationProposal(
        source_work=lin.source, target=target, edge_type="builds-on", basis_item=basis
    )
    return propose_relation(project, agent, p).relation_id


def _reasons(project: Project, rid: str) -> tuple[str, ...]:
    view = relation_view(project, rid)
    assert view is not None
    return view.stale_reasons


def test_fresh_relations_have_proposal_status(project: Project, agent: Actor, lin: Lineage) -> None:
    stated = _propose(project, agent, lin, lin.target5, lin.base)
    inferred = _propose(project, agent, lin, lin.target3, lin.base)
    one, two = relation_view(project, stated), relation_view(project, inferred)
    assert one is not None and two is not None
    assert (one.effective, one.stale_reasons, one.proposal_status) == (
        EdgeStatus.STATED,
        (),
        "stated",
    )
    assert (two.effective, two.status_reason) == (
        EdgeStatus.INFERRED,
        "target-differs",
    )
    assert one.reference_extraction_id == lin.rex and one.cited_entry == 5
    assert relation_view(project, "rel_01M68X9EG06809NC9ZQF9CAZZ0") is None


def _reconvert(project: Project) -> None:
    """A re-extraction on the same conversion is refused; convert the documents anew first."""
    run_convert(project, make_registry(StubConverter(version="9.9+lineage")))


def test_basis_correction_stales_and_reproposal_restores(  # Review Focus 5
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage
) -> None:
    # The basis is the base idea that cites nothing, so a new G1 extraction (which re-opens the
    # unit) does not make it stale; only its correction does.
    rid = _propose(project, agent, lin, lin.target5, lin.uncited_base)
    _reconvert(project)
    extract_references(project, agent, [lin.source], sources=lin.lookups.sources())
    fixed = [
        item("base-idea", P5, name="Plain text", statement="Plain text with no marker"),
        item("limitation", P4, name="long sequences", statement="very long sequences degrade"),
        item("addition", P2, name="softmax attention"),
    ]
    new_a, _ = record_both(
        project,
        ctr_a,
        ctr_b,
        lin.source,
        fixed,
        supersedes_a={0: lin.uncited_base, 1: lin.limitation},
        supersedes_b={0: lin.ids_b[2], 1: lin.ids_b[3]},
    )
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STALE
    assert "basis-superseded" in view.stale_reasons
    assert [r.relation_id for r in list_relations(project, statuses={EdgeStatus.STALE})] == [rid]
    again = _propose(project, agent, lin, lin.target5, new_a[0])
    assert again != rid
    assert [r.relation_id for r in list_relations(project, statuses=set(EdgeStatus))] == [again]


def test_amendment_removing_field_stales_relation(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    rid = _propose(project, agent, lin, lin.target5, lin.base)
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    schema = current.spec.contribution_schema
    narrowed = schema.model_copy(
        update={"fields": tuple(f for f in schema.fields if f != "cited_entry")}
    )
    spec = current.spec.model_copy(update={"contribution_schema": narrowed})
    amend_protocol(project, agent, spec, reason="narrow", semantic=True, effects={})
    assert "basis-stale" in _reasons(project, rid)


def test_new_g1_extraction_stales_relation(project: Project, agent: Actor, lin: Lineage) -> None:
    rid = _propose(project, agent, lin, lin.target5, lin.base)
    _reconvert(project)
    extract_references(project, agent, [lin.source], sources={})
    reasons = _reasons(project, rid)
    assert "references-superseded" in reasons and "basis-stale" in reasons
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STALE


def test_link_rejection_stales_stated_relation(  # Review Focus 1
    project: Project, agent: Actor, human: Actor, lin: Lineage
) -> None:
    rid = _propose(project, agent, lin, lin.target5, lin.base)
    payload = ReferenceResolutionDecided.model_validate(
        {
            "extraction_id": lin.rex,
            "ordinal": 5,
            "decision": "reject",
            "work_id": None,
            "rationale": "wrong paper",
            "quotes": [],
            "confirmed_by": "human",
        }
    )
    project.record([project.events.make("reference.resolution_decided", payload, human)])
    assert _reasons(project, rid) == ("link-changed",)
    assert rid not in {r.relation_id for r in list_relations(project)}
    # Re-proposing with the same, still live basis supersedes the stale relation.
    again = propose_relation(
        project,
        agent,
        RelationProposal(
            source_work=lin.source, target=lin.target5, edge_type="builds-on", basis_item=lin.base
        ),
    )
    assert again.written and again.relation_id != rid
    assert (again.status, again.status_reason) == ("inferred", "link-unconfirmed")


def test_default_list_excludes_inferred_stale_rejected(  # acceptance 9
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:
    _propose(project, agent, lin, lin.target5, lin.base)  # stated
    inferred = _propose(project, agent, lin, lin.target3, lin.base)
    assert {r.effective for r in list_relations(project)} <= {
        EdgeStatus.STATED,
        EdgeStatus.CONFIRMED,
    }
    assert inferred not in {r.relation_id for r in list_relations(project)}
    both = list_relations(project, statuses=set(EdgeStatus))
    assert {r.effective for r in both} == {EdgeStatus.STATED, EdgeStatus.INFERRED}
    assert {EdgeStatus.STATED, EdgeStatus.CONFIRMED} == DEFAULT_STATUSES


def test_confirmed_relation_appears_in_default_list(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:
    inferred = _propose(project, agent, lin, lin.target3, lin.base)
    decide_relation(project, other_session_human, inferred, LineageDecision.CONFIRM, "ok")
    [view] = list_relations(project)
    assert (view.relation_id, view.effective, view.decision) == (
        inferred,
        EdgeStatus.CONFIRMED,
        LineageDecision.CONFIRM,
    )


def test_rejected_is_hidden_and_wins_over_stale(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:
    rid = _propose(project, agent, lin, lin.target3, lin.base)
    decide_relation(project, other_session_human, rid, LineageDecision.REJECT, "no")
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.REJECTED
    assert list_relations(project) == []
    [shown] = list_relations(project, statuses={EdgeStatus.REJECTED})
    assert shown.relation_id == rid


def test_counts_cover_every_status(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:
    _propose(project, agent, lin, lin.target5, lin.base)
    rid = _propose(project, agent, lin, lin.target3, lin.base)
    counts = relation_counts(project)
    assert set(counts) == {"builds-on", "improves-on"}
    assert all(set(c) == {s.value for s in EdgeStatus} for c in counts.values())
    assert counts["builds-on"]["stated"] == 1 and counts["builds-on"]["inferred"] == 1
    assert sum(counts["improves-on"].values()) == 0
    decide_relation(project, other_session_human, rid, LineageDecision.REJECT, "no")
    assert relation_counts(project)["builds-on"]["rejected"] == 1


def test_relation_views_equal_relation_view(project: Project, agent: Actor, lin: Lineage) -> None:
    ids = [
        _propose(project, agent, lin, lin.target5, lin.base),
        _propose(project, agent, lin, lin.target3, lin.base),
    ]
    batch = relation_views(project, [*ids, "rel_01M68X9EG06809NC9ZQF9CAZZ0"])
    assert set(batch) == set(ids)
    assert all(batch[i] == relation_view(project, i) for i in ids)
    assert relation_views(project, []) == {}


def test_list_pages_in_sql_and_filters_by_work(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    _propose(project, agent, lin, lin.target5, lin.base)
    _propose(project, agent, lin, lin.target3, lin.base)
    every = set(EdgeStatus)
    page1 = list_relations(project, statuses=every, limit=1)
    page2 = list_relations(project, statuses=every, limit=1, offset=1)
    assert len(page1) == len(page2) == 1 and page1 != page2
    assert len(list_relations(project, statuses=every, work_id=lin.target5)) == 1
    assert list_relations(project, statuses=every, work_id="rf:nobody-00000000") == []
    assert list_relations(project, statuses=every, work_id=lin.source, limit=10)


def test_inferred_relation_records_its_reference_extraction(
    project: Project, agent: Actor, other_session_human: Actor, lin: Lineage
) -> None:  # review fix 2
    rid = _propose(project, agent, lin, lin.target3, lin.base)  # inferred: target differs
    view = relation_view(project, rid)
    assert view is not None
    assert (view.reference_extraction_id, view.cited_entry) == (lin.rex, 5)
    decide_relation(project, other_session_human, rid, LineageDecision.CONFIRM, "ok")
    _reconvert(project)
    extract_references(project, agent, [lin.source], sources={})
    stale = relation_view(project, rid)
    assert stale is not None and "references-superseded" in stale.stale_reasons
    assert stale.effective is EdgeStatus.STALE


def _resolved_to_b(project: Project, human: Actor, lin: Lineage) -> tuple[str, str]:
    [d] = contribution_agreement(project, human).disagreements
    resolve_contribution(
        project, human, d.work_id, d.row_key, "cited_entry", "b", "entry 3", Channel.CLI
    )
    return d.work_id, d.row_key


def test_new_g1_extraction_after_resolution_stales_confirmed_relation(
    project: Project, agent: Actor, human: Actor, other_session_human: Actor, disputed: Lineage
) -> None:  # review fix 1: the final item is unresolved afterwards
    _resolved_to_b(project, human, disputed)
    rid = _propose(project, agent, disputed, disputed.target5, disputed.base)  # inferred
    decide_relation(project, other_session_human, rid, LineageDecision.CONFIRM, "ok")
    _reconvert(project)
    extract_references(project, agent, [disputed.source], sources={})
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STALE
    assert rid not in {r.relation_id for r in list_relations(project)}


def test_re_resolving_the_cited_entry_stales_a_stated_relation(
    project: Project, agent: Actor, human: Actor, disputed: Lineage
) -> None:  # review fix 1: the final cited entry moved from 3 to 5
    work, row_key = _resolved_to_b(project, human, disputed)
    rid = _propose(project, agent, disputed, disputed.target3, disputed.base)
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STATED
    resolve_contribution(project, human, work, row_key, "cited_entry", "a", "entry 5", Channel.CLI)
    changed = relation_view(project, rid)
    assert changed is not None and changed.effective is EdgeStatus.STALE
    assert changed.stale_reasons == ("basis-changed",)

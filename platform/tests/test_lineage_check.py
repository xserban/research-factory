"""`check` findings of the lineage (slice 3b, plan G2-E, task 1)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable

import pytest

from factory.cli.render import contribution_status_lines
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.mcp import server as mcp_server
from factory.model.lineage import (
    EdgeStatus,
    LineageDecision,
    RelationProposal,
    RelationProposed,
)
from factory.model.notices import NoticeKind
from factory.model.project import RigorMode
from factory.model.references import LinkState, ReferenceResolutionDecided
from factory.model.screening import Channel, PassLabel
from factory.services import check as check_module
from factory.services.check import LEVELS, Finding, _findings_as, agent_view, check
from factory.services.context import Project
from factory.services.contributions import (
    ContributionStatus,
    NoItemUnit,
    contribution_agreement,
    contribution_audit_record,
    contribution_audit_sample,
    contribution_next,
    contribution_record,
    live_items,
)
from factory.services.extraction import ContributionBatch
from factory.services.ideas import propose_idea
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.reference_view import reference_view
from factory.services.relations import (
    decide_relation,
    list_relations,
    propose_relation,
    relation_view,
)
from tests.contribution_helpers import P1, P2, P3, P4, P5, item, not_stated
from tests.helpers import open_session
from tests.lineage_helpers import (
    ITEMS,
    Lineage,
    ctr_a,
    ctr_b,
    lin,
    record_both,
    screened,
    with_references,
    world,
)
from tests.lineage_payloads import REL, stated
from tests.test_contribution_agreement import _lorem
from tests.test_extraction_agreement import ext_a, ext_b
from tests.test_notice_effects import _observe

LINEAGE_CODES = (
    "contribution-missing-extraction",
    "contribution-stale",
    "contribution-schema-missing",
    "relation-stale",
    "relation-unconfirmed",
    "relation-uncited-base",
    "relation-without-basis",
    "idea-unconfirmed",
    "graph-extraction-missing",
    "contribution-error-ceiling",
    "contribution-closed-without-items",
)
MODES = (RigorMode.EXPLORATORY, RigorMode.PILOT, RigorMode.SYSTEMATIC)


def _found(project: Project, mode: RigorMode = RigorMode.PILOT) -> dict[str, Finding]:
    return {f.code: f for f in _findings_as(project, mode) if f.code in LINEAGE_CODES}


def _rel(project: Project, agent: Actor, lin: Lineage, target: str, basis: str | None) -> str:
    p = RelationProposal(
        source_work=lin.source, target=target, edge_type="builds-on", basis_item=basis
    )
    return propose_relation(project, agent, p).relation_id


def _park_everything(project: Project, ctr_a: Actor, ctr_b: Actor) -> None:
    for actor, label in ((ctr_a, PassLabel.A), (ctr_b, PassLabel.B)):
        served = contribution_next(project, actor, label).batch
        while isinstance(served, ContributionBatch):
            contribution_record(project, actor, served.task_id, [], finish=True, reason="parked")
            served = contribution_next(project, actor, label).batch


# --- One constructed case per code (acceptance 17) ---


def test_missing_extraction_names_unread_works(
    project: Project, lin: Lineage, world: list[str]
) -> None:
    hit = _found(project)["contribution-missing-extraction"]
    assert set(hit.refs) == {w for w in world if w != lin.source}
    assert lin.source not in hit.refs


def test_stale_after_amendment(project: Project, agent: Actor, lin: Lineage) -> None:
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    schema = current.spec.contribution_schema
    narrowed = schema.model_copy(
        update={"fields": tuple(f for f in schema.fields if f != "cited_entry")}
    )
    spec = current.spec.model_copy(update={"contribution_schema": narrowed})
    amend_protocol(project, agent, spec, reason="narrow", semantic=True, effects={})
    assert lin.source in _found(project)["contribution-stale"].refs


def test_schema_missing_when_g1_ran_without_a_declaration(
    project: Project, agent: Actor, screened: list[str]
) -> None:
    assert _found(project) == {}
    with_references(project, agent, screened[0])
    hit = _found(project)["contribution-schema-missing"]
    assert [m for m in MODES if "contribution-schema-missing" in _found(project, m)] == [
        RigorMode.PILOT,
        RigorMode.SYSTEMATIC,
    ]
    assert hit.refs == []


def test_relation_stale_and_unconfirmed_and_uncited(
    project: Project, agent: Actor, human: Actor, lin: Lineage, world: list[str]
) -> None:
    stated_id = _rel(project, agent, lin, lin.target5, lin.base)
    other = next(w for w in world if w != lin.source)
    inferred = _rel(project, agent, lin, other, lin.base)  # uncited-base, inferred
    _rel(project, agent, lin, lin.target3, lin.base)  # inferred, target differs
    found = _found(project)
    assert "relation-stale" not in found
    unconfirmed = found["relation-unconfirmed"]
    assert unconfirmed.message.startswith("2 ")  # one finding with the count
    assert set(unconfirmed.refs) == {inferred} | {r for r in unconfirmed.refs if r != stated_id}
    assert stated_id not in unconfirmed.refs
    assert found["relation-uncited-base"].refs == [inferred]
    project.record(
        [
            project.events.make(
                "reference.resolution_decided",
                ReferenceResolutionDecided.model_validate(
                    {
                        "extraction_id": lin.rex,
                        "ordinal": 5,
                        "decision": "reject",
                        "work_id": None,
                        "rationale": "wrong paper",
                        "quotes": [],
                        "confirmed_by": "human",
                    }
                ),
                human,
            )
        ]
    )
    assert _found(project)["relation-stale"].refs == [stated_id]


def test_stale_is_not_broken_chain(  # Review Focus 2, and the rejected link of carry-over 2
    project: Project, agent: Actor, human: Actor, lin: Lineage
) -> None:
    rid = _rel(project, agent, lin, lin.target5, lin.base)
    view = reference_view(project, lin.source)
    assert view is not None and view.entry(5) is not None
    project.record(
        [
            project.events.make(
                "reference.resolution_decided",
                ReferenceResolutionDecided.model_validate(
                    {
                        "extraction_id": lin.rex,
                        "ordinal": 5,
                        "decision": "reject",
                        "work_id": None,
                        "rationale": "wrong paper",
                        "quotes": [],
                        "confirmed_by": "human",
                    }
                ),
                human,
            )
        ]
    )
    after = reference_view(project, lin.source)
    assert after is not None
    entry = after.entry(5)
    assert entry is not None and entry.link_state is not LinkState.RESOLVED
    found = _found(project)
    assert found["relation-stale"].refs == [rid]
    assert "relation-without-basis" not in found


def test_without_basis_needs_a_hand_written_event(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    assert "relation-without-basis" not in _found(project)
    payload = RelationProposed.model_validate(
        stated(
            source_work=lin.source, target=lin.target5, resolved_target=lin.target5
        )  # basis and extraction unknown
    )
    project.record(
        [
            project.events.make(
                "relation.proposed",
                payload,
                agent,
                refs=[REL],
                input_blob=project.blobs.put_json({"by": "hand"}),
            )
        ]
    )
    assert _found(project)["relation-without-basis"].refs == [REL]


def test_idea_unconfirmed(project: Project, agent: Actor, lin: Lineage) -> None:
    ident = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    assert _found(project)["idea-unconfirmed"].refs == [ident]


def test_graph_extraction_missing(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage, world: list[str]
) -> None:
    other = next(w for w in world if w != lin.source)
    record_both(
        project, ctr_a, ctr_b, other, [not_stated("base-idea"), _lorem(), not_stated("limitation")]
    )
    assert _found(project)["graph-extraction-missing"].refs == [other]


def test_closed_without_items_is_listed(project: Project, ctr_a: Actor, lin: Lineage) -> None:
    served = contribution_next(project, ctr_a, PassLabel.A).batch
    assert isinstance(served, ContributionBatch)
    contribution_record(project, ctr_a, served.task_id, [], finish=True, reason="no paper text")
    hit = _found(project)["contribution-closed-without-items"]
    assert hit.refs == [served.records[0]["work_id"]]


def test_error_ceiling(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage
) -> None:
    _park_everything(project, ctr_a, ctr_b)
    contribution_agreement(project, human)
    assert "contribution-error-ceiling" not in _found(project)
    sampled = contribution_audit_sample(project, human, random_seed=11)
    for s in sampled.items:
        contribution_audit_record(
            project, human, sampled.audit_id, s.work_id, s.row_key, s.field, False, "", Channel.CLI
        )
    assert _found(project)["contribution-error-ceiling"].refs == [sampled.audit_id]


# --- Severities ---

SEVERITY = {
    "contribution-missing-extraction": ("warning", "warning", "error"),
    "contribution-stale": ("warning", "warning", "warning"),
    "contribution-schema-missing": (None, "warning", "error"),
    "relation-stale": ("warning", "warning", "warning"),
    "relation-unconfirmed": ("warning", "warning", "warning"),
    "relation-uncited-base": ("warning", "warning", "warning"),
    "relation-without-basis": ("error", "error", "error"),
    "idea-unconfirmed": ("warning", "warning", "warning"),
    "graph-extraction-missing": ("warning", "warning", "warning"),
    "contribution-error-ceiling": (None, "warning", "error"),
    "contribution-closed-without-items": ("warning", "warning", "warning"),
}


def test_severity_by_mode() -> None:
    assert set(SEVERITY) == set(LINEAGE_CODES)
    for code, levels in SEVERITY.items():
        assert LEVELS[code] == levels, code


# --- Properties of the whole ---


def test_untouched_project_has_no_lineage_findings(  # Review Focus 1
    project: Project, screened: list[str]
) -> None:
    for mode in MODES:
        assert _found(project, mode) == {}


def test_findings_carry_no_document_text(
    project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    _rel(project, agent, lin, lin.target3, lin.base)
    propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    texts = " ".join(f.message for f in _found(project).values())
    for needle in ("linear attention", "Alpha", "kernel", "Plain text", "very long sequences"):
        assert needle not in texts


def test_unconfirmed_is_one_finding_with_the_count(
    project: Project, agent: Actor, lin: Lineage
) -> None:
    for target in (lin.target3, lin.target5):
        _rel(project, agent, lin, target, lin.uncited_base)
    findings = [
        f for f in _findings_as(project, RigorMode.PILOT) if f.code == "relation-unconfirmed"
    ]
    assert len(findings) == 1 and findings[0].message.startswith("2 ")


def test_agent_view_withholds_the_ceiling_flag(
    project: Project, human: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage
) -> None:
    _park_everything(project, ctr_a, ctr_b)
    contribution_agreement(project, human)
    sampled = contribution_audit_sample(project, human, random_seed=11)
    for s in sampled.items:
        contribution_audit_record(
            project, human, sampled.audit_id, s.work_id, s.row_key, s.field, False, "", Channel.CLI
        )
    report = check(project)
    assert "contribution-error-ceiling" in {f.code for f in report.findings}
    seen = agent_view(report)
    assert "contribution-error-ceiling" not in {f.code for f in seen.findings}
    assert sampled.audit_id not in str(seen.model_dump())
    assert seen.ok == report.ok


def test_stale_row_beside_a_current_unit_is_tolerated(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, lin: Lineage
) -> None:
    """Carry-over 4: stale rows are never superseded, so a re-read unit leaves old stale rows
    live; the unit is current and is not reported stale."""
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    schema = current.spec.contribution_schema
    narrowed = schema.model_copy(
        update={"fields": tuple(f for f in schema.fields if f != "cited_entry")}
    )
    spec = current.spec.model_copy(update={"contribution_schema": narrowed})
    amend_protocol(project, agent, spec, reason="narrow", semantic=True, effects={})
    assert lin.source in _found(project)["contribution-stale"].refs
    plain = [  # new anchors: the stale rows stay live and own the old ones
        item("base-idea", P3, name="ImageNet"),
        item("addition", P3, name="top-1"),
        item("limitation", P5, name="Plain text"),
    ]
    record_both(project, ctr_a, ctr_b, lin.source, plain)
    assert any(i.stale for i in live_items(project, include_stale=True))  # old rows stay live
    assert "contribution-stale" not in _found(project)


def test_status_lines_print_zero_item_closures_with_their_reason() -> None:
    status = ContributionStatus(
        units={},
        items_by_kind={},
        not_stated={},
        markers={},
        no_references=[],
        other_conversion=[],
        closed_without_items=[
            NoItemUnit(
                work_id="rf:a", pass_label=PassLabel.A, task_id="tsk_1", reason="scanned image"
            ),
            NoItemUnit(work_id="rf:b", pass_label=PassLabel.B, task_id="tsk_2", reason=None),
        ],
    )
    lines = contribution_status_lines(status)
    assert "closed without items: 2" in lines
    assert "  rf:a  pass A  reason: scanned image" in lines
    assert "  rf:b  pass B  reason: -" in lines


@pytest.mark.anyio
async def test_check_is_refused_to_a_pass_session(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    lin: Lineage,
    ctr_a: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return ctr_a.session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)  # this session read a contribution pass
    async with open_session(settings, clock) as client:
        out = await client.call("check", project="demo")
    assert out["ok"] is False and out["errors"][0]["field"] == "session"


def test_retracted_basis_leaves_default_views(  # living-C follow-up
    project: Project, agent: Actor, lin: Lineage
) -> None:
    """An edge whose basis item belongs to a work the notices exclude from the synthesis is
    stale (reason `basis-retracted`): it leaves the default views and `check` lists it."""
    rid = _rel(project, agent, lin, lin.target5, lin.base)
    assert [r.relation_id for r in list_relations(project)] == [rid]
    _observe(project, lin.source, NoticeKind.RETRACTION, "10.1/retraction")
    view = relation_view(project, rid)
    assert view is not None and view.effective is EdgeStatus.STALE
    assert "basis-retracted" in view.stale_reasons
    assert list_relations(project) == []
    assert _found(project)["relation-stale"].refs == [rid]


def test_both_audits_fold_into_one_neutral_marker(
    project: Project,
    agent: Actor,
    human: Actor,
    ext_a: Actor,
    ext_b: Actor,
    ctr_a: Actor,
    ctr_b: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision 52 for both audits: one `extraction-audit-reported` warning whenever either has
    labels; the findings, their order and `ok` do not depend on either ceiling."""
    from factory.services.check import agent_check
    from factory.services.extraction_audit import extraction_audit_record, extraction_audit_sample
    from tests.test_extraction_agreement import _both, _r

    monkeypatch.setattr(check_module, "_rigor_mode", lambda project: RigorMode.SYSTEMATIC)
    with_references(project, agent, world[0])

    def rows_for(work: str) -> list:  # type: ignore[type-arg]
        return [] if work == world[0] else [_r()]

    _both(project, ext_a, ext_b, rows_for, rows_for)
    record_both(project, ctr_a, ctr_b, world[0], ITEMS)
    _park_everything(project, ctr_a, ctr_b)
    contribution_agreement(project, human)
    ev = extraction_audit_sample(project, human, random_seed=2)
    co = contribution_audit_sample(project, human, random_seed=2)

    def label(correct: bool) -> None:
        for s in ev.items:
            extraction_audit_record(
                project, human, ev.audit_id, s.work_id, s.row_key, s.field, correct, "", Channel.CLI
            )
        for s in co.items:
            contribution_audit_record(
                project, human, co.audit_id, s.work_id, s.row_key, s.field, correct, "", Channel.CLI
            )

    label(True)
    below = agent_check(project)
    label(False)
    above = agent_check(project)
    assert [f.model_dump() for f in below.findings] == [f.model_dump() for f in above.findings]
    assert below.ok == above.ok
    markers = [f for f in above.findings if f.code == "extraction-audit-reported"]
    assert len(markers) == 1 and set(markers[0].refs) == {ev.audit_id, co.audit_id}
    assert not any(c.isdigit() for c in markers[0].message)
    assert "contribution-error-ceiling" not in {f.code for f in above.findings}

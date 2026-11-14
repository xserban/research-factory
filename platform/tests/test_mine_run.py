"""`mine_next`, `mine_record` and `mine_status` over a registered miner (M-C, task 7)."""

# ruff: noqa: F811
import json

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mining.spec import spec_to_json
from factory.model.extraction import ExtractedRowInput, FieldInput, MinerScope
from factory.model.screening import Channel, PassLabel
from factory.services.check import check
from factory.services.context import Project
from factory.services.evidence_report import evidence_report
from factory.services.extraction import (
    MineBatch,
    extract_next,
    extract_record,
    live_rows,
    unit_states,
)
from factory.services.extraction_agreement import (
    extraction_agreement,
    final_rows,
    grouped_rows,
    independence_counts,
    resolve_extraction,
)
from factory.services.gates import gate_acts
from factory.services.mining import mine_next, mine_record, mine_status, register_miner
from factory.services.modules.default import default_modules
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    SESSION_M2,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_pass,
    mine_row,
    miner_actor,
)

A, B = PassLabel.A, PassLabel.B


@pytest.fixture
def mina() -> Actor:
    return miner_actor(SESSION_M1, "claude-opus-5-5")


@pytest.fixture
def minb() -> Actor:
    return miner_actor(SESSION_M2, "claude-sonnet-5-5")


def _report(project: Project) -> str:
    """The evidence report as JSON without the protocol version it names: listing a miner
    amends the protocol, which changes `P@` and nothing else in the report."""
    body = evidence_report(project).model_dump(mode="json")
    body.pop("project_protocol_id")
    return json.dumps(body, sort_keys=True)


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def test_mine_next_refused_until_listed(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, mina, VISION_NAME, 1, A, exploratory=True)  # not registered
    assert raised.value.issues[0].field == "miners"
    register_miner(project, agent, spec_to_json(method_vision()))
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        mine_next(project, mina, VISION_NAME, 1, A, exploratory=True)  # registered, not listed
    assert raised.value.issues[0].field == "miners"
    assert _events(project) == before  # nothing written: no pass opened, no join


def test_task_content_has_anchor_ids_not_text(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    batch = mine_next(project, mina, VISION_NAME, 1, A, exploratory=True).batch
    assert isinstance(batch, MineBatch)
    assert (batch.miner, batch.version) == (VISION_NAME, 1)
    assert batch.anchors == ("s3.p1", "t1")
    assert len(batch.digest) == 16
    assert batch.field_kinds["direction"].startswith("enum: higher | lower")
    assert "Lorem ipsum" not in json.dumps(batch.model_dump(mode="json"))  # ids, not text
    assert batch.claims is False and batch.required == ["metric", "value"]


def test_full_dual_run_of_vision_result_miner(
    project: Project, agent: Actor, human: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    scope = MinerScope(VISION_NAME)
    worked = mine_pass(project, mina, A, lambda w: [mine_row()])
    assert worked
    mine_pass(project, minb, B, lambda w: [mine_row("lower" if w == worked[0] else "higher")])
    assert {s.state for s in unit_states(project, scope=scope)} == {"current"}
    assert live_rows(project) == []  # the evidence scope saw none of it
    assert len(live_rows(project, scope=scope)) == 2 * len(worked)
    agreement = extraction_agreement(project, human, scope=scope)
    assert [(d.work_id, d.field) for d in agreement.disagreements] == [(worked[0], "direction")]
    assert agreement.dual_works == len(worked)
    status = mine_status(project)[0]
    assert (status.name, status.units, status.closed, status.open) == (
        VISION_NAME,
        2 * len(worked),
        2 * len(worked),
        0,
    )
    assert status.agreement is not None and status.agreement < 1.0
    assert mine_status(project, with_agreement=False)[0].agreement is None
    disputed = agreement.disagreements[0]
    with pytest.raises(FactoryValidationError):  # an agent may not resolve
        resolve_extraction(
            project,
            agent,
            worked[0],
            disputed.row_key,
            "direction",
            "a",
            "why",
            Channel.CLI,
            scope=scope,
        )
    resolve_extraction(
        project,
        human,
        worked[0],
        disputed.row_key,
        "direction",
        "a",
        "pass A is right",
        Channel.CLI,
        scope=scope,
    )
    finals = final_rows(project, scope=scope)
    assert len(finals) == len(worked)
    assert {f.status for f in finals} == {"agreed", "resolved"}
    assert len(list(gate_acts(project, "mine.resolve"))) == 1
    assert list(gate_acts(project, "extraction.resolve")) == []


def test_pass_sessions_see_their_own_pass_only(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    worked = mine_pass(project, mina, A, lambda w: [mine_row()])
    mine_pass(project, minb, B, lambda w: [mine_row()])
    own = mine_status(project, session=mina.session, with_agreement=False)
    assert len(own) == 1 and own[0].units == len(worked) and own[0].agreement is None
    assert own[0].rows == len(worked)
    everyone = mine_status(project, with_agreement=False)[0]
    assert everyone.units == 2 * len(worked) and everyone.rows == 2 * len(worked)


def test_registered_miner_rows_invisible_to_evidence(
    project: Project,
    agent: Actor,
    mina: Actor,
    minb: Actor,
    ext_a: Actor,
    ext_b: Actor,
    world: list[str],
) -> None:
    _both(project, ext_a, ext_b)
    report_before = _report(project)
    final_before = final_rows(project)
    grouped_before = grouped_rows(project).model_dump_json()
    counts_before = independence_counts(final_before)
    assert final_before
    list_miner(project, agent)
    mine_pass(project, mina, A, lambda w: [mine_row()])
    mine_pass(project, minb, B, lambda w: [mine_row()])
    assert final_rows(project, scope=MinerScope(VISION_NAME))
    assert final_rows(project) == final_before
    assert grouped_rows(project).model_dump_json() == grouped_before
    assert independence_counts(final_rows(project)) == counts_before
    assert _report(project) == report_before


def test_failed_plan_d_row_reports_only_plan_d_issues(
    project: Project, agent: Actor, mina: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    batch = mine_next(project, mina, VISION_NAME, 1, A, exploratory=True).batch
    assert batch is not None
    row = mine_row()
    fields = dict(row.fields)
    fields["metric"] = FieldInput(value="Lorem", anchor="t1.r3.c1", quote="not in the cell")
    fields["direction"] = FieldInput(value="higher")  # no evidence: only the kind check minds
    result = mine_record(project, mina, batch.task_id, [ExtractedRowInput(fields=fields)])
    reasons = {i.field: i.reason for e in result.rows.rejected for i in e.issues}
    assert reasons == {"fields.metric.quote": "quote-not-in-anchor"}
    fields["metric"] = row.fields["metric"]
    result = mine_record(project, mina, batch.task_id, [ExtractedRowInput(fields=fields)])
    reasons = {i.field: i.reason for e in result.rows.rejected for i in e.issues}
    assert reasons == {"fields.direction.quote": "enum-needs-quote"}
    assert not result.rows.written


def test_the_two_record_tools_refuse_each_others_tasks(
    project: Project, agent: Actor, mina: Actor, ext_a: Actor, world: list[str]
) -> None:
    evidence = extract_next(project, ext_a, A).batch
    assert evidence is not None
    with pytest.raises(FactoryValidationError) as raised:
        mine_record(project, ext_a, evidence.task_id, [mine_row()])
    assert raised.value.issues[0].field == "task_id"
    list_miner(project, agent)
    batch = mine_next(project, mina, VISION_NAME, 1, A, exploratory=True).batch
    assert batch is not None
    with pytest.raises(FactoryValidationError) as raised:
        extract_record(project, mina, batch.task_id, [mine_row()])
    assert "mine_record" in raised.value.issues[0].reason


def test_registry_ownership_still_exhaustive() -> None:
    registry = default_modules()
    assert registry.owner_of_event("miner.registered") == "mining"
    assert registry.owner_of_table("miners") == "mining"
    assert registry.owner_of_section("miners") == "mining"
    assert registry.owner_of_task_kind("mine_a") == "mining"
    assert registry.owner_of_check("mine-pending") == "mining"
    assert registry.owner_of_check("mine-single") == "mining"
    assert registry.gate("mine.resolve").act_events == ("extraction.resolved",)
    assert registry.levels()["mine-single"] == (None, "warning", "error")


def test_mine_pending_is_reported_with_counts_only(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    list_miner(project, agent)
    found = [f for f in check(project).findings if f.code == "mine-pending"]
    assert len(found) == 1 and found[0].severity == "warning"  # every unit is still queued
    assert "Lorem" not in found[0].message and found[0].message.startswith("miner m-vision")
    mine_pass(project, mina, A, lambda w: [mine_row()])
    mine_pass(project, minb, B, lambda w: [mine_row()])
    codes = {f.code for f in check(project).findings}
    assert "mine-pending" not in codes and "mine-single" not in codes


def test_a_half_sample_reports_the_works_mined_once(
    project: Project, agent: Actor, mina: Actor, minb: Actor, world: list[str]
) -> None:
    spec = list_miner(project, agent)
    from factory.services.protocol import amend_protocol, current_protocol
    from tests.miner_helpers import use

    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"miners": (use(spec, dual_extract_sample=0.5),)}),
        reason="sample half",
        semantic=True,
        effects={},
    )
    mine_pass(project, mina, A, lambda w: [mine_row()])
    mine_pass(project, minb, B, lambda w: [mine_row()])
    single = [f for f in check(project).findings if f.code == "mine-single"]
    assert len(single) == 1 and single[0].severity == "warning"
    assert 0 < len(single[0].refs) < len(world)

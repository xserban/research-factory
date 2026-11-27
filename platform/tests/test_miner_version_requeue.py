"""A new miner version re-queues the works closed under the previous one (live pilot bug): units
are keyed by miner name, so version is judged from the task's `schema_ref`, and the rows of
another version neither occupy row keys of the new version nor count against it."""

# ruff: noqa: F811
from dataclasses import replace

import pytest

from factory.events.envelope import Actor
from factory.mining.spec import EnumKind, MinerField, spec_to_json
from factory.model.extraction import MinerScope
from factory.model.screening import PassLabel
from factory.services import protocol as protocol_service
from factory.services.context import Project
from factory.services.extraction import live_rows, stale_extractions, unit_states
from factory.services.mining import mine_record, mine_status, register_miner
from factory.services.protocol import amend_protocol, current_protocol
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    method_vision,
    mine_exploratory,
    mine_pass,
    mine_row,
    miner_actor,
    use,
)

A = PassLabel.A


def _states(project: Project, scope: MinerScope) -> set[str]:
    """The states of the pass A units (pass B is never mined here, its units stay queued)."""
    return {s.state for s in unit_states(project, scope=scope) if s.pass_label is A}


def _list_v2(project: Project, agent: Actor) -> None:
    """Register version 2 (one more `direction` value) and list it in place of version 1."""
    base = method_vision(version=2)
    fields = tuple(
        MinerField(f.name, f.group, EnumKind(("higher", "lower", "equal")), required=f.required)
        if f.name == "direction"
        else f
        for f in base.fields
    )
    spec = replace(base, fields=fields)
    register_miner(project, agent, spec_to_json(spec))
    current = current_protocol(project)
    assert current is not None
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"miners": (use(spec),)}),
        reason="list miner version 2",
        semantic=True,
        effects={},
    )


@pytest.mark.parametrize("amendment_stales", [True, False])
def test_new_version_requeues_and_records_and_counts_only_v2(
    project: Project,
    agent: Actor,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
    amendment_stales: bool,
) -> None:
    """With `amendment_stales` False the protocol amendment carries no `miner_stale` rule (as in
    the pilot, where works closed under version 1 stayed current): only the task's schema
    reference tells the versions apart."""
    mina = miner_actor(SESSION_M1, "claude-opus-5-5")
    list_miner(project, agent)
    scope = MinerScope(VISION_NAME)
    worked = mine_pass(project, mina, A, lambda w: [mine_row()])
    assert worked
    assert _states(project, scope) == {"current"}
    v1_rows = {r.extraction_id for r in live_rows(project, scope=scope)}
    assert len(v1_rows) == len(worked)

    if not amendment_stales:
        monkeypatch.setattr(protocol_service, "miner_stale", lambda *a, **k: ())
    _list_v2(project, agent)

    assert _states(project, scope) == {"stale"}
    assert {s.reason for s in unit_states(project, scope=scope) if s.pass_label is A} == {"schema"}
    assert stale_extractions(project, scope=scope) == v1_rows

    served: list[str] = []
    for _ in range(len(worked) + 1):
        batch = mine_exploratory(project, mina, VISION_NAME, 2, A).batch
        if batch is None:
            break
        assert batch.version == 2
        result = mine_record(
            project, mina, batch.task_id, [mine_row("equal")], finish=True, reason=None
        )
        assert result.completed, result.rows.rejected
        served.append(batch.records[0]["work_id"])
    assert sorted(served) == sorted(worked)

    assert _states(project, scope) == {"current"}
    assert stale_extractions(project, scope=scope) == v1_rows
    fresh = [r for r in live_rows(project, scope=scope) if r.extraction_id not in v1_rows]
    assert len(fresh) == len(worked)
    status = mine_status(project)[0]
    assert (status.closed, status.stale) == (len(worked), 0)
    assert all(r.task_id for r in fresh)

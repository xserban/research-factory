# ruff: noqa: F401, F811
"""The contribution allow-list: `contribution_schema.works` restricts which included works
contribution mining serves (a protocol amendment, so a human decision on the record)."""

import pytest
from sqlalchemy import text

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.model.extraction import Scope
from factory.model.protocol import ExtractionSchema, protocol_version
from factory.model.screening import PassLabel
from factory.services.context import Project
from factory.services.contributions import contribution_next, contribution_status
from factory.services.extraction import ContributionBatch, scope_population, unit_states
from factory.services.protocol import amend_protocol, current_protocol
from tests.contribution_helpers import C, ctr_a, ctr_b, screened, world

A, B = PassLabel.A, PassLabel.B


def _set_works(project: Project, agent: Actor, works: tuple[str, ...] | None) -> None:
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    schema = current.spec.contribution_schema.model_copy(update={"works": works})
    amend_protocol(
        project,
        agent,
        current.spec.model_copy(update={"contribution_schema": schema}),
        reason="restrict contribution mining",
        semantic=False,
        effects={},
    )


def _served(project: Project, actor: Actor, label: PassLabel = A) -> str | None:
    batch = contribution_next(project, actor, label).batch
    assert batch is None or isinstance(batch, ContributionBatch)
    return None if batch is None else str(batch.records[0]["work_id"])


def test_absent_list_serves_every_included_work(
    project: Project, ctr_a: Actor, world: list[str]
) -> None:
    served = contribution_next(project, ctr_a, A)
    assert served.allow_list is None and "allow_list" not in served.model_dump(mode="json")
    assert contribution_status(project).allow_list is None
    assert scope_population(project, C) == sorted(world)


def test_list_restricts_served_works(
    project: Project, agent: Actor, ctr_a: Actor, world: list[str]
) -> None:
    assert len(world) >= 2
    _set_works(project, agent, (world[1],))
    served = contribution_next(project, ctr_a, A)
    assert isinstance(served.batch, ContributionBatch)
    assert served.batch.records[0]["work_id"] == world[1]
    assert served.allow_list is not None
    assert served.allow_list.listed == 1 and served.allow_list.eligible == 1
    assert served.allow_list.not_eligible == []
    assert served.remaining == 1
    assert scope_population(project, C) == [world[1]]


def test_pass_b_and_states_read_the_same_population(
    project: Project, agent: Actor, ctr_a: Actor, ctr_b: Actor, world: list[str]
) -> None:
    _set_works(project, agent, (world[1],))
    for label in (A, B):
        assert {s.work_id for s in unit_states(project, scope=C) if s.pass_label is label} == {
            world[1]
        }
    assert _served(project, ctr_a, A) == world[1]
    assert _served(project, ctr_b, B) == world[1]


def test_status_reports_the_list_and_unserveable_ids(
    project: Project, agent: Actor, world: list[str]
) -> None:
    with project.index.connect() as conn:
        ids = [str(r[0]) for r in conn.execute(text("SELECT work_id FROM works")).all()]
    outside = next(w for w in sorted(ids) if w not in world)
    _set_works(project, agent, (world[0], outside))
    status = contribution_status(project)
    state = status.allow_list
    assert state is not None
    assert (state.listed, state.eligible, state.not_eligible) == (2, 1, [outside])
    assert sum(status.units.values()) == 2  # one work, two passes


def test_unknown_work_id_is_refused(project: Project, agent: Actor, world: list[str]) -> None:
    with pytest.raises(FactoryValidationError) as caught:
        _set_works(project, agent, ("W-does-not-exist",))
    assert any(i.field == "contribution_schema.works" for i in caught.value.issues)


def test_list_is_refused_on_the_evidence_schema(
    project: Project, agent: Actor, world: list[str]
) -> None:
    current = current_protocol(project)
    assert current is not None and current.spec.extraction_schema is not None
    schema = current.spec.extraction_schema.model_copy(update={"works": (world[0],)})
    with pytest.raises(FactoryValidationError):
        amend_protocol(
            project,
            agent,
            current.spec.model_copy(update={"extraction_schema": schema}),
            reason="x",
            semantic=False,
            effects={},
        )


def test_list_is_sorted_and_unique() -> None:
    schema = ExtractionSchema(
        pack="contribution", pack_version=1, fields=("name",), works=("b", "a", "b")
    )
    assert schema.works == ("a", "b")


def test_unset_list_leaves_the_dump_and_version_as_before(
    project: Project, agent: Actor, world: list[str]
) -> None:
    current = current_protocol(project)
    assert current is not None and current.spec.contribution_schema is not None
    assert "works" not in current.spec.contribution_schema.model_dump(mode="json")
    before = protocol_version(current.spec)
    _set_works(project, agent, (world[0],))
    after = current_protocol(project)
    assert after is not None and after.protocol_id != before
    assert after.spec.contribution_schema is not None
    assert after.spec.contribution_schema.works == (world[0],)
    _set_works(project, agent, None)
    back = current_protocol(project)
    assert back is not None and back.protocol_id == before

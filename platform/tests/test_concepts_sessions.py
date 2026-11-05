"""A session that wrote a concept or a `uses` link cannot join a pass (decision 37 item 15)."""

# ruff: noqa: F401, F811

from __future__ import annotations

from collections.abc import Callable

import pytest

from factory.errors import FactoryValidationError
from factory.events.reader import read_all
from factory.model.extraction import Scope
from factory.model.intuition import ConceptInput, UseBasisInput
from factory.model.screening import PassLabel
from factory.services.concepts import define_concept, propose_concept_link
from factory.services.context import Project
from factory.services.extraction import join_extraction_pass
from factory.services.screening import join_pass
from tests.intuition_helpers import IWorld, ctr_a, ctr_b, iw, lin, screened, world, writer_actor

TEXTBOOK = {"kind": "textbook", "citation": "Textbook, chapter 3"}


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _refused_everywhere(project: Project, actor: object) -> None:
    joins: list[Callable[[], object]] = [
        lambda: join_pass(project, actor, PassLabel.A),  # type: ignore[arg-type]
        lambda: join_extraction_pass(project, actor, PassLabel.A),  # type: ignore[arg-type]
        lambda: join_extraction_pass(
            project,
            actor,  # type: ignore[arg-type]
            PassLabel.A,
            scope=Scope.CONTRIBUTION,
        ),
    ]
    for join in joins:
        before = _events(project)
        with pytest.raises(FactoryValidationError) as e:
            join()
        assert [i.field for i in e.value.issues] == ["session"]
        assert "intuition" in e.value.issues[0].reason
        assert _events(project) == before


def test_session_that_only_called_concept_propose_cannot_join(project: Project, iw: IWorld) -> None:
    actor = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W6A", "proposer")
    define_concept(project, actor, ConceptInput.model_validate({"name": "kernel"}))
    _refused_everywhere(project, actor)


def test_session_that_only_called_concept_link_cannot_join(project: Project, iw: IWorld) -> None:
    cid = define_concept(
        project, iw.human, ConceptInput.model_validate({"name": "kernel", "source": TEXTBOOK})
    )
    actor = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W6B", "linker")
    propose_concept_link(project, actor, iw.source, cid, UseBasisInput(), note="reads like it")
    _refused_everywhere(project, actor)


def test_a_session_that_never_touched_the_layer_still_joins(project: Project, iw: IWorld) -> None:
    fresh = writer_actor("01JZ9Q3K5M7N8P0R2S4T6V8W6C", "other").model_copy(
        update={"skill": "rf-extract@1a2b3c4d"}
    )
    join_extraction_pass(project, fresh, PassLabel.A)

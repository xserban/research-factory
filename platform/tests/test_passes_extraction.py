# ruff: noqa: F811
"""A screening session cannot relay an extraction human act (slice M ruling 21, decision 55).

The world is that of `test_extraction_agreement`: its `human` shares a session with the screening
agents."""

import pytest

from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.screening import Channel
from factory.services.context import Project
from factory.services.extraction_agreement import extraction_agreement, resolve_extraction
from tests.extraction_helpers import _both, _r, ext_a, ext_b, screened, world  # noqa: F401

pytestmark = pytest.mark.slow


def test_screening_session_cannot_relay_extraction_resolution(
    project: Project, human: Actor, ext_a: Actor, ext_b: Actor, world: list[str]
) -> None:
    odd = world[0]
    _both(project, ext_a, ext_b, b=lambda w: [_r(task="detection")] if w == odd else [_r()])
    (d,) = extraction_agreement(project, human).disagreements
    before = len(read_all(project.paths.events_dir, project.catalog))
    with pytest.raises(FactoryValidationError) as e:
        resolve_extraction(project, human, odd, d.row_key, "task", "a", "x", Channel.MCP)
    assert e.value.issues[0].field == "channel"
    assert len(read_all(project.paths.events_dir, project.catalog)) == before
    resolve_extraction(project, human, odd, d.row_key, "task", "a", "x", Channel.CLI)

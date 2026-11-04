"""A log written before slice 4b replays to the state hash the base projection gave it.

The fixture log is synthetic (two records of one paper, one other, merged by `dedup_run`). The
expected hash was computed by the projection at the base commit a2fb6bc, before the watch tables
and the derived lookup tables existed; only `PROJECTION_VERSION` (in `meta`, which the hash
leaves out) may differ.
"""

import shutil
from pathlib import Path

from factory.clock import FixedClock
from factory.config import Settings
from factory.services.context import open_project
from tests.helpers import SESSION, T0

FIXTURE = Path(__file__).parent / "fixtures" / "old_log_events"
BASE_STATE_HASH = "sha256:277c8dd2fc194ffa23e39b70b3a2ca9da36b5d398e80d66dd6ea7eecbcc2ff76"


def test_old_log_state_hash_is_unchanged(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE, tmp_path / "projects" / "demo" / "events")
    project = open_project(
        Settings(root=tmp_path, user="obd"), "demo", session=SESSION, clock=FixedClock(T0)
    )
    assert project.index.rebuild() == BASE_STATE_HASH
    assert project.index.state_hash() == BASE_STATE_HASH

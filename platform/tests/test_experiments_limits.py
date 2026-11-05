"""The access limit is fixed at the freeze, and the plan in force is re-read at it (review S2, S3,
X11, X12), plus the guards of the services that the fold hides (X2, C3) and the scrubbing of the
experiment view (M15)."""

# ruff: noqa: F401, F811

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.hypotheses.design import cell_hash
from factory.mcp import server as mcp_server
from factory.model.hypothesis_plan import HypothesisPlan
from factory.services.context import Project
from factory.services.experiments import (
    design_experiment,
    experiment_view,
    freeze_experiment,
    unlock_experiment,
    unlock_nonce,
)
from factory.services.hypotheses import has_confirmatory_evidence
from factory.services.protocol import amend_protocol, current_protocol
from factory.services.xruns import ingest_results, register_run, xrun_view
from tests.experiment_helpers import XW, cell, design, frozen_design, results_file, xw
from tests.extraction_helpers import SESSION_A
from tests.helpers import install_skill, open_session
from tests.hypothesis_helpers import DRAFTER, HW, gw, hw
from tests.test_mcp_cards import SESSION_E, _session


def _fields(err: pytest.ExceptionInfo[FactoryValidationError]) -> list[tuple[str, str]]:
    return [(i.field, i.reason) for i in err.value.issues]


def set_plan(project: Project, human: Actor, **plan: int) -> None:
    """The researcher amends `hypothesis_plan` of the protocol."""
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_copy(update={"hypothesis_plan": HypothesisPlan(**plan)})
    amend_protocol(project, human, spec, reason="plan", semantic=True, effects={})


def read(project: Project, human: Actor, tmp_path: Path, exp: str, nonce: str, n: int) -> str:
    run = register_run(project, DRAFTER, exp, cell("treatment"))
    path = results_file(tmp_path, run, nonce=nonce, name=f"r{n}.json")
    ingest_results(project, human, path)
    return run


def test_the_design_limit_is_the_one_frozen_and_read(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    set_plan(project, human, test_access_limit=3)  # S2, X11
    exp = frozen_design(project, human, xw, baselines=[], test_access_limit=2)
    view = experiment_view(project, exp)
    assert view is not None and view.access_limit == 2
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None
    read(project, human, tmp_path, exp, nonce, 1)
    read(project, human, tmp_path, exp, nonce, 2)
    view = experiment_view(project, exp)
    assert view is not None and view.deviations == []  # two reads are the allowance
    third = read(project, human, tmp_path, exp, nonce, 3)
    kept = xrun_view(project, third)
    assert kept is not None and kept.flags == ("test-reused",)
    view = experiment_view(project, exp)
    assert view is not None and [d.kind for d in view.deviations] == ["test-reuse"]


def test_a_later_amendment_cannot_raise_the_frozen_limit(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw, baselines=[])  # the plan's limit is 1
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None
    set_plan(project, human, test_access_limit=5)  # X12: even the researcher's amendment
    read(project, human, tmp_path, exp, nonce, 1)
    second = read(project, human, tmp_path, exp, nonce, 2)
    kept = xrun_view(project, second)
    assert kept is not None and kept.flags == ("test-reused",)
    view = experiment_view(project, exp)
    assert view is not None and view.access_limit == 1
    assert [d.kind for d in view.deviations] == ["test-reuse"]


def test_the_freeze_rechecks_the_design_under_the_plan_now_in_force(
    project: Project, human: Actor, xw: XW
) -> None:
    exp, _ = design_experiment(project, DRAFTER, xw.design(baselines=[]))  # three seeds: pilot
    set_plan(project, human, min_seeds=5)  # S3
    with pytest.raises(FactoryValidationError) as err:
        freeze_experiment(project, human, exp)
    assert _fields(err) == [("seeds", "at-least-5")]
    view = experiment_view(project, exp)
    assert view is not None and view.state == "draft"


def test_a_run_cannot_be_registered_against_a_superseded_design(
    project: Project, human: Actor, xw: XW
) -> None:
    first, _ = design_experiment(project, DRAFTER, xw.design(baselines=[]))  # X2
    design_experiment(
        project, DRAFTER, xw.design(baselines=[], seeds=[1, 2, 3, 4]), supersedes=first
    )
    with pytest.raises(FactoryValidationError) as err:
        register_run(project, DRAFTER, first, cell("ablation:no-norm", split="dev"))
    assert _fields(err) == [("experiment_id", "superseded")]


def test_a_registered_confirmatory_run_that_is_not_reported_is_not_evidence(
    project: Project, human: Actor, xw: XW, tmp_path: Path
) -> None:
    exp = frozen_design(project, human, xw, baselines=[])  # C3
    unlock_experiment(project, human, exp)
    nonce = unlock_nonce(project, exp)
    assert nonce is not None
    register_run(project, DRAFTER, exp, cell("treatment"))
    assert has_confirmatory_evidence(project, xw.hid) is False
    read(project, human, tmp_path, exp, nonce, 1)
    assert has_confirmatory_evidence(project, xw.hid) is True


@pytest.mark.anyio
async def test_the_experiment_view_is_scrubbed_of_held_out_identifiers(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    human: Actor,
    xw: XW,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-experiment")  # M15
    secret = "10.1234/held-out-doi"
    exp, _ = design_experiment(project, DRAFTER, xw.design(baselines=[], notes=f"see {secret}"))
    monkeypatch.setattr(mcp_server, "_held_out_tokens", lambda _p, _w=True: {secret})
    _session(monkeypatch, SESSION_E)
    async with open_session(settings, clock) as client:
        viewed = await client.call("experiment_view", project="demo", experiment_id=exp)
    assert viewed["ok"] is True, viewed
    assert secret not in json.dumps(viewed)
    assert "[withheld]" in viewed["data"]["design"]["notes"]

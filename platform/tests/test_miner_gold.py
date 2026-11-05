"""Human gold labels of a miner calibration (M-D, task 3)."""

# ruff: noqa: F811
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryValidationError
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp import server as mcp_server
from factory.model.extraction import ExtractedRowInput, FieldInput
from factory.model.screening import Channel, PassLabel
from factory.services.context import Project
from factory.services.miner_gold import calibration_labels, label_miner_calibration
from factory.services.miners import calibration_of, draw_miner_calibration
from factory.services.mining import mine_next
from tests.cli_helpers import _env
from tests.extraction_helpers import _both, ext_a, ext_b, screened, world  # noqa: F401
from tests.helpers import install_skill, open_session
from tests.miner_helpers import (
    SESSION_M1,
    VISION_NAME,
    list_miner,
    mine_row,
    miner_actor,
)

CLI, MCP = Channel.CLI, Channel.MCP


def _events(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


def _drawn(project: Project, agent: Actor, human: Actor) -> tuple[str, list[str]]:
    list_miner(project, agent)
    drawn = draw_miner_calibration(project, human, VISION_NAME, 1, random_seed=3)
    return drawn.calibration_id, [u.work_id for u in drawn.units]


def _human(session: str) -> Actor:
    return Actor(kind="human", id="obd", user="obd", session=session)


def test_gold_row_verified_like_agent_row(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    bad = mine_row()
    bad.fields["metric"] = FieldInput(value="Lorem", anchor="t1.r3.c1", quote="Nowhere stated")
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(project, human, cal, works[0], [bad], channel=CLI)
    assert raised.value.issues[0].field.startswith("rows.0.fields.metric")
    assert _events(project) == before
    assert calibration_labels(project, cal) == {}


def test_gold_row_is_stored_as_verified(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    label_miner_calibration(project, human, cal, works[0], [mine_row()], channel=CLI)
    rows = calibration_labels(project, cal)[works[0]]
    assert len(rows) == 1 and rows[0].row_key.startswith("rk_")
    assert rows[0].fields["metric"].quote == "Lorem" and rows[0].fields["value"].canonical


def test_agent_cannot_label(project: Project, agent: Actor, human: Actor, world: list[str]) -> None:
    cal, works = _drawn(project, agent, human)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(project, agent, cal, works[0], [mine_row()], channel=CLI)
    assert raised.value.issues[0].field == "actor"
    assert _events(project) == before


def test_proposer_session_cannot_relay(
    project: Project, agent_other: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent_other, human)  # the proposer is the session S2
    relay = _human(agent_other.session)
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(project, relay, cal, works[0], [mine_row()], channel=MCP)
    assert raised.value.issues[0].field == "session"
    assert _events(project) == before
    # a human at the terminal is not a relay by the proposer's session
    label_miner_calibration(project, relay, cal, works[0], [mine_row()], channel=CLI)


def test_pass_session_cannot_relay(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    worker = miner_actor(SESSION_M1, "claude-opus-5-5")
    mine_next(project, worker, VISION_NAME, 1, PassLabel.A)  # joins a miner pass
    before = _events(project)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(
            project, _human(SESSION_M1), cal, works[0], [mine_row()], channel=MCP
        )
    assert raised.value.issues[0].field == "channel"
    assert _events(project) == before


def test_unit_outside_sample_and_unknown_calibration_refused(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    outside = next(w for w in world if w not in works)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(project, human, cal, outside, [mine_row()], channel=CLI)
    assert raised.value.issues[0].field == "work_id"
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(
            project, human, "mcl_01JZ9Q3K5M7N8P0R2S4T6V8W1E", works[0], [mine_row()], channel=CLI
        )
    assert raised.value.issues[0].field == "calibration_id"


def test_rows_and_empty_must_agree(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    for rows, empty in (([mine_row()], True), ([], False)):
        with pytest.raises(FactoryValidationError) as raised:
            label_miner_calibration(project, human, cal, works[0], rows, empty=empty, channel=CLI)
        assert raised.value.issues[0].field == "rows"
    label_miner_calibration(project, human, cal, works[1], [], empty=True, channel=CLI)
    assert calibration_labels(project, cal) == {works[1]: ()}


def test_duplicate_gold_rows_refused(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    cal, works = _drawn(project, agent, human)
    with pytest.raises(FactoryValidationError) as raised:
        label_miner_calibration(
            project, human, cal, works[0], [mine_row(), mine_row()], channel=CLI
        )
    assert raised.value.issues[0].field == "rows.1"


def test_relabel_supersedes(project: Project, agent: Actor, human: Actor, world: list[str]) -> None:
    cal, works = _drawn(project, agent, human)
    label_miner_calibration(project, human, cal, works[0], [mine_row("higher")], channel=CLI)
    first = calibration_labels(project, cal)[works[0]][0].fields["direction"].value
    label_miner_calibration(project, human, cal, works[0], [mine_row("lower")], channel=CLI)
    second = calibration_labels(project, cal)[works[0]]
    assert (first, second[0].fields["direction"].value) == ("higher", "lower")
    assert len(second) == 1
    kinds = [e.type for e in read_all(project.paths.events_dir, project.catalog)]
    assert kinds.count("miner.calibration_labelled") == 2  # both stay in the log


def test_label_replays(project: Project, agent: Actor, human: Actor, world: list[str]) -> None:
    cal, works = _drawn(project, agent, human)
    label_miner_calibration(project, human, cal, works[0], [mine_row()], channel=CLI)
    before = project.index.state_hash()
    project.index.rebuild()
    assert project.index.state_hash() == before
    assert calibration_of(project, VISION_NAME, 1) is not None
    assert works[0] in calibration_labels(project, cal)


def test_the_gate_is_declared_and_human() -> None:
    from factory.modules.contract import PolicyKind
    from factory.services.modules.default import default_modules

    gate = default_modules().gate("miner.calibration_label")
    assert gate.floor is PolicyKind.HUMAN
    assert gate.act_events == ("miner.calibration_labelled",)
    assert default_modules().owner_of_event("miner.calibration_labelled") == "mining"


_ = ExtractedRowInput
runner = CliRunner()


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_cli_draw_label_and_retire(
    settings: Settings, project: Project, agent: Actor, world: list[str], tmp_path: Path
) -> None:
    list_miner(project, agent)
    draw = ("miner", "calibrate", "draw", VISION_NAME, "1")
    code, out, err = _cli(settings.root, *draw, "--seed", "4")
    assert code == 0 and "calibration mcl_" in out and "seed 4" in out, err
    cal = out.split()[1].rstrip(":")
    work = out.splitlines()[1]
    rows = tmp_path / "gold.json"
    rows.write_text(json.dumps([mine_row().model_dump(mode="json")]))
    code, out, err = _cli(settings.root, "miner", "calibrate", "label", cal, work, str(rows))
    assert code == 0 and "1 gold row(s)" in out, err
    assert len(calibration_labels(project, cal)[work]) == 1
    code, out, err = _cli(settings.root, "miner", "calibrate", "label", cal, work, "--empty")
    assert code == 0 and "empty" in out, err
    assert calibration_labels(project, cal)[work] == ()  # the later label won
    code, _, err = _cli(settings.root, *draw)
    assert code == 1 and "calibration" in err  # a second draw is refused
    code, out, err = _cli(settings.root, "miner", "retire", VISION_NAME, "1", "--reason", "done")
    assert code == 0 and "retired" in out, err
    code, _, err = _cli(settings.root, "miner", "retire", "contribution", "1", "--reason", "x")
    assert code == 1 and "built-in" in err


def _session(monkeypatch: pytest.MonkeyPatch, session: str) -> None:
    class Ids:
        def __init__(self, _clock: object) -> None: ...

        def ulid(self) -> str:
            return session

    monkeypatch.setattr(mcp_server, "IdGenerator", Ids)


async def _relay(
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
    session: str,
    cal: str,
    work: str,
) -> dict[str, Any]:
    _session(monkeypatch, session)
    async with open_session(settings, clock) as client:
        return await client.call(
            "miner_calibration_label",
            project="demo",
            calibration_id=cal,
            work_id=work,
            rows=[mine_row().model_dump(mode="json")],
        )


@pytest.mark.anyio
async def test_mcp_relay_is_refused_to_pass_and_proposer_sessions(
    settings: Settings,
    project: Project,
    agent_other: Actor,
    human: Actor,
    clock: FixedClock,
    world: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_skill(settings, "rf-extract")
    cal, works = _drawn(project, agent_other, human)  # proposer: session S2
    mine_next(project, miner_actor(SESSION_M1, "claude-opus-5-5"), VISION_NAME, 1, PassLabel.A)
    before = _events(project)
    for session in (SESSION_M1, agent_other.session):
        out = await _relay(settings, clock, monkeypatch, session, cal, works[0])
        assert out["ok"] is False and out["errors"][0]["field"] == "session"
    assert _events(project) == before
    out = await _relay(settings, clock, monkeypatch, "01JZ9Q3K5M7N8P0R2S4T6V8W2Z", cal, works[0])
    assert out["ok"] is True, out
    assert len(calibration_labels(project, cal)[works[0]]) == 1

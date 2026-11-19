"""`factory leads candidates|queue|stats`: read-only, labelled, and the same figures as the
service (R-05)."""

# ruff: noqa: F811
import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.model.lead_engine import SOURCES
from factory.services.context import Project
from factory.services.lead_candidates import lead_candidates
from factory.services.lead_queue import lead_queue
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.lead_engine_helpers import engine_world

runner = CliRunner()
KNOBS = ("--layer", "all", "--technique-min-works", "1")


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["leads", *args], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_every_output_is_labelled_and_json_equals_the_service(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    for args in (("candidates",), ("queue",), ("stats",)):
        extra = KNOBS if args[0] != "stats" else ()
        code, out, err = _run(settings.root, *args, *extra)
        assert code == 0, (args, err)
        assert out.startswith("EXPLORATORY:"), args
    code, out, err = _run(settings.root, "candidates", "--format", "json", *KNOBS)
    assert code == 0, err
    want = lead_candidates(project, layer="all", technique_min_works=1)
    assert json.loads(out) == json.loads(want.model_dump_json(by_alias=True))
    code, out, err = _run(settings.root, "queue", "--format", "json", *KNOBS)
    assert code == 0, err
    got = json.loads(out)
    assert got["exploratory"] is True and got["parameters"]["balance"] == 1
    again = lead_queue(project, layer="all", technique_min_works=1)
    assert got == json.loads(again.model_dump_json(by_alias=True))
    code, out, err = _run(settings.root, "stats", "--format", "json")
    assert code == 0 and json.loads(out)["recorded"] == 0, err


def test_the_options_reach_the_service(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    engine_world(project, agent, human, world)
    code, out, err = _run(
        settings.root,
        "queue",
        "--format",
        "json",
        "--sources",
        "technique-gap,claims-limitation",
        "--order-by",
        "support,score",
        "--top",
        "1",
        "--no-balance",
        "--exclude-prior",
        "--per-source",
        "5",
        "--max-co-works",
        "1",
        *KNOBS,
    )
    assert code == 0, err
    data = json.loads(out)
    assert data["order_by"] == ["support", "score"] and len(data["items"]) == 1
    p = data["parameters"]
    assert p["sources"] == ["technique-gap", "claims-limitation"] and p["top"] == 1
    assert p["balance"] == 0 and p["exclude_prior"] == 1 and p["per_source"] == 5
    assert p["max_co_works"] == 1 and p["technique_min_works"] == 1
    code, out, err = _run(
        settings.root, "queue", "--format", "json", "--per-source-top", "1", *KNOBS
    )
    assert code == 0, err
    assert (
        len(json.loads(out)["items"]) == len({i["source"] for i in json.loads(out)["items"]})
        and json.loads(out)["parameters"]["per_source_top"] == 1
    )
    assert SOURCES  # the default sources are all four


def test_bad_options_are_refused_and_there_is_no_recording_command(
    settings: Settings, project: Project
) -> None:
    for args in (
        ("queue", "--order-by", "nope"),
        ("queue", "--top", "0"),
        ("candidates", "--sources", "nope"),
        ("candidates", "--sources", ","),
        ("queue", "--format", "xml"),
        ("queue", "--no-balance", "--per-source-top", "2"),
    ):
        code, _, _ = _run(settings.root, *args)
        assert code != 0, args
    code, _, _ = _run(settings.root, "record")
    assert code != 0

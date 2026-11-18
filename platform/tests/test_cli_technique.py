"""`factory technique ...`: read-only, labelled, and the same figures as the service (R-05)."""

# ruff: noqa: F811
import json
from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.services import technique_graph as tg
from factory.services.context import Project
from tests.cli_helpers import _env
from tests.extraction_helpers import screened, world  # noqa: F401
from tests.test_technique_graph_project import _mine, _setup

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["technique", *args], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def test_the_cli_equals_the_service_and_every_output_is_labelled(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ordered = _setup(project, agent, human, world)
    _mine(project, ordered)
    code, out, err = _run(settings.root, "landscape", "--format", "json", "--min-co-works", "1")
    assert code == 0, err
    expected = tg.technique_landscape(project, min_co_works=1)
    assert json.loads(out) == json.loads(expected.model_dump_json(by_alias=True))
    assert json.loads(out)["exploratory"] is True
    for args in (
        ("landscape",),
        ("show", "ide-01"),
        ("candidates",),
        ("neighbors", "ide-01"),
        ("gaps", "--from-stage", "ideation", "--to-stage", "experiment", "--min-works", "1"),
        ("combinations", "--min-works", "1"),
        ("challenges",),
    ):
        code, out, err = _run(settings.root, *args)
        assert code == 0, (args, err)
        assert out.startswith("EXPLORATORY:"), args
    code, out, err = _run(
        settings.root, "combinations", "--min-works", "1", "--rank-by", "bridge", "--top", "1",
        "--format", "json",
    )  # fmt: skip
    assert code == 0, err
    data = json.loads(out)
    assert data["parameters"]["rank_by"] == "bridge" and len(data["combinations"]) <= 1
    assert all("score" in c and "weights" in c["score"] for c in data["combinations"])
    code, out, err = _run(settings.root, "combinations", "--rank-by", "novelty")
    assert code != 0 and "rank_by" in (out + err)
    code, out, _ = _run(settings.root, "show", "ide-01")
    assert "Lorem ipsum dolor sit amet." in out and "s3.p1" in out
    code, out, err = _run(settings.root, "show", "nope")
    assert code != 0 and "unknown approach" in (out + err)


def test_the_cli_is_the_researchers_own_view_and_names_held_out_works(
    settings: Settings, project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    """Open choice, documented: no `technique` CLI command calls `require_pass_opened` or scrubs,
    as for every command in `CLI_READS` (decision 37 item 9: the CLI is the researcher's own and
    shows corpus works, held-out ones included). The MCP path refuses before a pass opens and
    scrubs. An agent reaching the CLI is held back by the CLI permission gate, not here."""
    ordered = _setup(project, agent, human, world)
    _mine(project, ordered)
    code, out, err = _run(settings.root, "show", "ide-02")
    assert code == 0, err
    assert out.startswith("EXPLORATORY:")
    assert ordered[1] in out and "not available yet" not in out
    code, out, err = _run(settings.root, "candidates")
    assert code == 0, err
    assert out.startswith("EXPLORATORY:")

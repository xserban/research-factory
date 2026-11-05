"""The `factory relations` and `factory ideas` commands (plan G2-C, task 6): human acts, CLI."""

# ruff: noqa: F401, F811

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor, Event
from factory.events.reader import read_all
from factory.model.lineage import RelationProposal
from factory.services.context import Project
from factory.services.ideas import propose_idea
from factory.services.relations import propose_relation
from tests.lineage_helpers import Lineage, ctr_a, ctr_b, lin, screened, world
from tests.test_cli import _env

runner = CliRunner()


def _run(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, list(args), env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _of(project: Project, kind: str) -> list[Event]:
    return [e for e in read_all(project.paths.events_dir, project.catalog) if e.type == kind]


def _propose(
    project: Project, agent: Actor, lin: Lineage, target: str, note: str | None = None
) -> str:
    p = RelationProposal(
        source_work=lin.source, target=target, edge_type="builds-on", basis_item=lin.base, note=note
    )
    return propose_relation(project, agent, p).relation_id


def test_relations_list_shows_effective_status_and_reason(
    settings: Settings, project: Project, agent: Actor, lin: Lineage
) -> None:
    stated = _propose(project, agent, lin, lin.target5)
    inferred = _propose(project, agent, lin, lin.target3)
    code, out, err = _run(settings.root, "relations", "list")
    assert code == 0, err
    assert stated in out and inferred not in out  # default: stated and confirmed only
    code, out, _ = _run(settings.root, "relations", "list", "--status", "inferred")
    assert inferred in out and "inferred" in out and "target-differs" in out
    code, out, _ = _run(
        settings.root, "relations", "list", "--status", "inferred", "--status", "stated"
    )
    assert stated in out and inferred in out
    code, out, err = _run(settings.root, "relations", "list", "--status", "bogus")
    assert code != 0


def test_relations_confirm_and_reject_write_human_events(
    settings: Settings, project: Project, agent: Actor, lin: Lineage
) -> None:
    inferred = _propose(project, agent, lin, lin.target3)
    code, _, err = _run(settings.root, "relations", "confirm", inferred, "--rationale", "checked")
    assert code == 0, err
    [decided] = _of(project, "relation.decided")
    assert decided.actor.kind == "human" and decided.payload["decision"] == "confirm"
    code, out, _ = _run(settings.root, "relations", "list")
    assert inferred in out and "confirmed" in out
    code, _, err = _run(settings.root, "relations", "reject", inferred, "--rationale", "wrong")
    assert code == 0, err
    assert [e.payload["decision"] for e in _of(project, "relation.decided")] == [
        "confirm",
        "reject",
    ]
    code, _, err = _run(
        settings.root, "relations", "confirm", "rel_01M68X9EG06809NC9ZQF9CAZZ0", "--rationale", "x"
    )
    assert code == 1 and "unknown-relation" in err


def test_ideas_define_confirm_merge_unmerge(
    settings: Settings, project: Project, agent: Actor, lin: Lineage, world: list[str]
) -> None:
    code, out, err = _run(
        settings.root,
        "ideas",
        "define",
        "Linear attention",
        "--origin",
        lin.source,
        "--name-item",
        lin.base,
        "--member",
        lin.source,
    )
    assert code == 0, err
    first = out.strip().split()[-1]
    second = propose_idea(project, agent, "linear attention", lin.source, lin.base, [lin.source])
    for ident in (first, second):
        code, _, err = _run(settings.root, "ideas", "confirm", ident, "--rationale", "named there")
        assert code == 0, err
    _, before, _ = _run(settings.root, "ideas", "list")
    assert first in before and second in before
    code, _, err = _run(settings.root, "ideas", "merge", first, second, "--reason", "same name")
    assert code == 0, err
    _, merged, _ = _run(settings.root, "ideas", "list")
    assert first not in merged and second in merged
    code, _, err = _run(settings.root, "ideas", "unmerge", first, "--reason", "split")
    assert code == 0, err
    _, after, _ = _run(settings.root, "ideas", "list")
    assert after == before


def test_ideas_list_all_and_candidates(
    settings: Settings, project: Project, agent: Actor, lin: Lineage
) -> None:
    idea = propose_idea(project, agent, "Linear attention", lin.source, lin.base, [lin.source])
    _, out, _ = _run(settings.root, "ideas", "list")
    assert idea not in out
    _, out, _ = _run(settings.root, "ideas", "list", "--all")
    assert idea in out and "proposed" in out
    code, out, err = _run(
        settings.root, "ideas", "candidates", "--origin", lin.target5, "--name", "linear attention"
    )
    assert code == 0, err
    assert lin.source in out and "name-in-item" in out

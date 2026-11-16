"""`factory references` and `factory snowball`: a human decides, plans rank the candidates."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory.cli.main import app
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.protocol import SnowballPlan
from factory.services.context import Project
from factory.services.references import extract_references, list_references
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _env
from tests.document_helpers import fetched_document, make_registry, promoted_works, run_convert
from tests.references_service_helpers import Lookups, bib_html, oa_item
from tests.test_snowball_round import BODY_A, BODY_B, ENTRIES_A, ENTRIES_B, PLAN, _amend, _lookups

runner = CliRunner()


def _cli(root: Path, *args: str) -> tuple[int, str, str]:
    rest = [a for a in args if a not in ("--project", "demo")]
    result = runner.invoke(app, ["--project", "demo", *rest], env=_env(root))
    return result.exit_code, result.stdout, result.stderr


def _use(monkeypatch: pytest.MonkeyPatch, lookups: Lookups) -> None:
    mapping: Mapping[str, SourceFactory] = lookups.sources()
    monkeypatch.setattr("factory.cli.main.lookup_sources", lambda: mapping)


def _count(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


@pytest.fixture
def extracted(project: Project, corpus: None, agent: Actor) -> Project:
    work_a, work_b = promoted_works(project)[:2]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    fetched_document(project, work_b, bib_html(ENTRIES_B, BODY_B))
    run_convert(project, make_registry())
    extract_references(project, agent, None, sources=_lookups().sources())
    return project


def test_extract_and_status_counts_sum_to_entries(
    project: Project,
    corpus: None,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_a = promoted_works(project)[0]
    fetched_document(project, work_a, bib_html(ENTRIES_A, BODY_A))
    run_convert(project, make_registry())
    _use(monkeypatch, _lookups())
    code, out, _ = _cli(
        settings.root, "references", "extract", "--work", work_a, "--project", "demo"
    )
    assert code == 0 and "1 extraction" in out, out
    code, out, _ = _cli(settings.root, "references", "status", "--project", "demo")
    assert code == 0
    figures = {
        k: int(v)
        for k, v in (line.split(": ") for line in out.splitlines() if ": " in line)
        if v.isdigit()
    }
    assert figures["entries"] == len(ENTRIES_A)
    parts = ("resolved", "unconfirmed", "ambiguous", "unresolved")
    assert sum(figures[p] for p in parts) == figures["entries"]


def test_list_filters_by_state(extracted: Project, settings: Settings) -> None:
    code, out, _ = _cli(
        settings.root, "references", "list", "--state", "resolved", "--project", "demo"
    )
    assert code == 0 and out.strip() and "resolved" in out
    body = [line for line in out.splitlines() if not line.startswith("(")]
    assert body and all(" resolved " in line for line in body)
    code, _, err = _cli(
        settings.root, "references", "list", "--state", "maybe", "--project", "demo"
    )
    assert code == 1 and "state" in err


def test_decide_confirm_as_human_writes_event(
    project: Project, corpus: None, agent: Actor, settings: Settings
) -> None:
    fetched_document(
        project,
        promoted_works(project)[0],
        bib_html(["B. Lee. Efficient reed transformers v2. Reed Conference, 2021."], ["x"]),
    )
    run_convert(project, make_registry())
    lookups = Lookups(openalex=[oa_item("Efficient Reed Transformers", "Bo Lee", 2021, "W501")])
    extract_references(project, agent, None, sources=lookups.sources())
    [item] = list_references(project, state=None, work_id=None, after=0, limit=10).items
    before = _count(project)
    code, out, _ = _cli(
        settings.root,
        "references",
        "decide",
        item.extraction_id,
        str(item.ordinal),
        "--confirm",
        "--rationale",
        "Same paper; the entry adds a version suffix.",
        "--entry-quote",
        "Efficient reed transformers v2",
        "--candidate-quote",
        "Efficient Reed Transformers",
        "--project",
        "demo",
    )
    assert code == 0, out
    assert _count(project) == before + 1
    [decided] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "reference.resolution_decided"
    ]
    assert decided.actor.kind == "human" and decided.payload["confirmed_by"] == "human"
    # Exactly one of --confirm / --reject.
    code, _, err = _cli(
        settings.root,
        "references",
        "decide",
        item.extraction_id,
        str(item.ordinal),
        "--rationale",
        "r",
        "--entry-quote",
        "a",
        "--candidate-quote",
        "b",
        "--project",
        "demo",
    )
    assert code == 2 and "--confirm" in err

    code, out, _ = _cli(
        settings.root,
        "references",
        "decide",
        item.extraction_id,
        str(item.ordinal),
        "--clear",
        "--rationale",
        "decided in error",
        "--project",
        "demo",
    )
    assert code == 0 and "cleared" in out


def test_snowball_plan_output_lists_candidates_ranked(
    extracted: Project, agent: Actor, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _count(extracted)
    code, out, _ = _cli(settings.root, "snowball", "plan", "backward", "--project", "demo")
    assert code == 0, out
    assert "snowball_plan" in out  # the pilot protocol declares no plan yet: the gap is printed
    assert _count(extracted) == before
    _amend(extracted, agent, PLAN)
    code, out, _ = _cli(settings.root, "snowball", "plan", "backward", "--project", "demo")
    assert code == 0 and "allowed" in out and "snowball_plan" not in out
    lines = [line for line in out.splitlines() if line.startswith("  cited by ")]
    counts = [int(line.split()[2]) for line in lines]
    assert lines and counts == sorted(counts, reverse=True)
    assert _count(extracted) == before + 1  # only the amendment
    bad = _cli(settings.root, "snowball", "plan", "sideways", "--project", "demo")
    assert bad[0] != 0


def test_snowball_run_and_compare(
    extracted: Project, agent: Actor, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _amend(extracted, agent, SnowballPlan(max_backward_rounds=2, max_forward_rounds=1))
    _use(monkeypatch, _lookups())
    code, out, _ = _cli(settings.root, "snowball", "run", "backward", "--project", "demo")
    assert code == 0 and "round snw_" in out, out
    round_id = next(w for w in out.split() if w.startswith("snw_")).rstrip(":,")
    code, out, _ = _cli(settings.root, "snowball", "compare", round_id, "--project", "demo")
    assert code == 0 and "both" in out

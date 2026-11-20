import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.model.decisions import DecisionLevel
from factory.model.fulltext import Route
from factory.model.protocol import PressElement, PressFinding
from factory.model.screening import Channel, PassLabel, ScreeningItem, ScreeningPhase, Verdict
from factory.model.search import QueryKind, QuerySpec
from factory.model.seed import SeedKind, SeedSpec
from factory.model.work import ProvenanceMethod
from factory.services.agreement import screen_agreement
from factory.services.calibration import calibration_items, label_calibration
from factory.services.context import Project
from factory.services.fulltext import fetch_fulltext
from factory.services.fulltext_import import import_folder
from factory.services.project import init_project
from factory.services.protocol import current_protocol, press_review
from factory.services.question import current_question
from factory.services.screening import screen_next, screen_record
from factory.services.search import list_works, register_query, run_query
from factory.services.seeds import add_seeds, explain_seed_miss, split_seeds
from factory.sources.registry import SourceFactory
from tests.cli_helpers import _cli_env, _env, runner
from tests.fulltext_helpers import _build, _pdf, _promoted, _routes
from tests.helpers import (
    FAKE_PAGES,
    S2,
    SESSION,
    FakeSource,
    _of_type,
    _setup,
    bind_ids,
    openalex_item,
    ready_protocol,
    record_pilot_question,
)


def test_init_status_rebuild(tmp_path: Path) -> None:
    env = _env(tmp_path)
    init = runner.invoke(app, ["init", "demo", "--mode", "pilot"], env=env)
    assert init.exit_code == 0
    assert init.stdout == "initialised demo (pilot)\n"

    status = runner.invoke(app, ["status", "--json"], env=env)
    assert status.exit_code == 0
    st = json.loads(status.stdout)
    assert st["slug"] == "demo" and st["events_total"] == 1

    out = runner.invoke(app, ["rebuild"], env=env)
    assert out.exit_code == 0
    assert re.fullmatch(r"state sha256:[0-9a-f]{64}\n", out.stdout)


def test_rebuild_output_is_stable(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "demo"], env=env)
    first = runner.invoke(app, ["rebuild"], env=env)
    second = runner.invoke(app, ["rebuild"], env=env)
    assert first.exit_code == 0 and second.exit_code == 0
    assert first.stdout == second.stdout


def test_init_invalid_slug_exit_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "Bad"], env=_env(tmp_path))
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "slug:" in result.stderr
    assert not (tmp_path / "projects").exists()


def test_invalid_user_exit_1(tmp_path: Path) -> None:
    env = {"FACTORY_ROOT": str(tmp_path), "FACTORY_USER": "Bad User", "FACTORY_PROJECT": None}
    result = runner.invoke(app, ["init", "demo"], env=env)
    assert result.exit_code == 1
    assert "user:" in result.stderr


def test_ambiguous_project_exit_2(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    runner.invoke(app, ["init", "b"], env=env)
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 2
    assert result.stderr.strip() == "several projects: a, b; pass --project"


def test_no_project_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["rebuild"], env=_env(tmp_path))
    assert result.exit_code == 2
    assert result.stderr.strip() == "no project; run factory init"


def test_explicit_project_option(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    runner.invoke(app, ["init", "b"], env=env)
    result = runner.invoke(app, ["--project", "b", "status", "--json"], env=env)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["slug"] == "b"


def test_unknown_explicit_project_exit_1(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "a"], env=env)
    result = runner.invoke(app, ["--project", "ghost", "status"], env=env)
    assert result.exit_code == 1
    assert result.stderr.strip() == "unknown project: ghost"


def test_status_human_output(tmp_path: Path) -> None:
    env = _env(tmp_path)
    runner.invoke(app, ["init", "demo", "--mode", "systematic"], env=env)
    result = runner.invoke(app, ["status"], env=env)
    assert result.exit_code == 0
    assert result.stdout == (
        "project: demo\n"
        "rigor mode: systematic\n"
        "tier: not declared\n"
        "autonomy level: attended\n"
        "stage: scoping\n"
        "events: 1\n"
        "question: none\n"
        "protocol: none\n"
        "seeds: 0 positive (not split), 0 negative, 0 unresolved\n"
        "tasks: open 0 / claimed 0 / expired 0 / completed 0\n"
        "calibration: drawn 0, labelled 0; gate required; passed A no, B no\n"
        "pass A: not opened\n"
        "pass B: not opened\n"
        "agreement: not available until both passes finish\n"
        "stale decisions: 0\n"
        "cannot-assess to resolve: title-abstract 0\n"
        "audit: none sampled\n"
        "chase rounds: 0\n"
        "admitted seeds: 0\n"
        "works: 0 (records 0, merges 0)\n"
        "searches: 0 runs (complete 0 / partial 0 / failed 0 / interrupted 0)\n"
    )


def test_status_shows_works_searches_and_shortfalls(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd")
    clock = FixedClock(datetime(2026, 10, 31, 12, 0, tzinfo=UTC))
    project = init_project(settings, "demo", "exploratory", session=SESSION, clock=clock)
    # The fake source reports 5 records and delivers 3: the shortfall must be shown.
    sources: dict[str, SourceFactory] = {
        "fake": SourceFactory(FakeSource.kinds, lambda _s, _c: FakeSource(FAKE_PAGES, reported=5))
    }
    spec = QuerySpec(source="fake", kind=QueryKind.KEYWORD, text="attention")
    query_id = register_query(project, project.human_actor(), spec, sources=sources)
    summary = run_query(project, query_id, sources=sources)

    result = runner.invoke(app, ["status"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-3:] == [
        "works: 3 (records 3, merges 0)",
        "searches: 1 runs (complete 1 / partial 0 / failed 0 / interrupted 0)",
        f"shortfall: {summary.run_id} fake 3/5 \u2014 2 of 5 reported not delivered",
    ]


def test_serve_is_registered(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--help"], env=_env(tmp_path))
    assert result.exit_code == 0
    for command in ("init", "rebuild", "status", "serve"):
        assert command in result.stdout


# --- Question, seeds, protocol: the human CLI (held-out roles are shown here only) ---


def _seed_one(project: Project, agent: Actor, sources: Any, n: int, kind: SeedKind) -> None:
    spec = SeedSpec(kind=kind, cite=f"Paper {n}", doi=f"10.1000/p{n}")
    item = openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )
    add_seeds(
        project,
        agent,
        [spec],
        sources=sources(openalex=[item]),
        decision_ids=bind_ids(project, agent, DecisionLevel.SEEDS),
    )


def test_seeds_cli_shows_held_out_roles(
    project: Project, agent: Actor, mock_sources: Any, settings: Settings
) -> None:
    record_pilot_question(project, agent)
    for n in (1, 2, 3):
        _seed_one(project, agent, mock_sources, n, SeedKind.POSITIVE)
    _seed_one(project, agent, mock_sources, 9, SeedKind.NEGATIVE)
    drawn = split_seeds(project, random_seed=7)

    result = runner.invoke(app, ["seeds"], env=_cli_env(settings.root))
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["id", "kind", "role", "resolution", "check"]
    for held in drawn.held_out:
        [row] = [line for line in lines if line.startswith(held)]
        assert "held-out" in row
    for dev in drawn.development:
        [row] = [line for line in lines if line.startswith(dev)]
        assert "development" in row
    negative = next(line for line in lines if line.startswith("NEG01"))
    assert negative.split()[2] == "unsplit"


def test_seeds_split_and_explain_cli(
    project: Project, agent: Actor, mock_sources: Any, settings: Settings
) -> None:
    record_pilot_question(project, agent)
    for n in (1, 2, 3):
        _seed_one(project, agent, mock_sources, n, SeedKind.POSITIVE)
    env = _cli_env(settings.root)

    split = runner.invoke(app, ["seeds", "split", "--random-seed", "7"], env=env)
    assert split.exit_code == 0, split.stderr
    assert split.stdout == "split drawn with random seed 7\n"
    again = runner.invoke(app, ["seeds", "split"], env=env)
    assert again.exit_code == 1
    assert "already drawn" in again.stderr

    explain = runner.invoke(
        app,
        ["seeds", "explain", "SEED01", "--route", "citation-chase", "--reason", "Not indexed."],
        env=env,
    )
    assert explain.exit_code == 0, explain.stderr
    assert explain.stdout == "explained SEED01 (citation-chase)\n"


def test_confirm_press_cli(
    project: Project, agent: Actor, human: Actor, mock_sources: Any, settings: Settings
) -> None:
    protocol_id = ready_protocol(project, agent, human, mock_sources, press=False)
    finding = PressFinding(
        element=PressElement.TEXT_WORDS, finding="Add a synonym.", severity="minor"
    )
    review_id = press_review(project, agent, protocol_id, (finding,))
    env = _cli_env(settings.root)

    wrong_count = runner.invoke(
        app, ["protocol", "confirm-press", review_id, "--response", "a", "--response", "b"], env=env
    )
    assert wrong_count.exit_code == 1
    assert "responses" in wrong_count.stderr

    confirmed = runner.invoke(
        app, ["protocol", "confirm-press", review_id, "--response", "Accepted."], env=env
    )
    assert confirmed.exit_code == 0, confirmed.stderr
    assert confirmed.stdout == f"confirmed {review_id}\n"
    protocol = current_protocol(project)
    assert protocol is not None and protocol.press == "confirmed"


def test_status_shows_question_protocol_and_seeds(
    project: Project, agent: Actor, human: Actor, mock_sources: Any, settings: Settings
) -> None:
    env = _cli_env(settings.root)
    empty = runner.invoke(app, ["status"], env=env).stdout.splitlines()
    assert "question: none" in empty
    assert "protocol: none" in empty
    assert "seeds: 0 positive (not split), 0 negative, 0 unresolved" in empty

    protocol_id = ready_protocol(project, agent, human, mock_sources)
    question = current_question(project)
    assert question is not None
    lines = runner.invoke(app, ["status"], env=env).stdout.splitlines()
    assert f"question: {question.question_id}" in lines
    assert f"protocol: {protocol_id} (ready, PRESS confirmed)" in lines
    assert "seeds: 3 positive (split drawn), 0 negative, 0 unresolved" in lines


def _screen_passes(project: Project, pass_a: Actor, pass_b: Actor) -> None:
    """Both passes screen to the end. A includes every work; B excludes the random works numbered
    in multiples of four under EX01, outside the calibration set, so the passes disagree on them."""
    for label, actor in ((PassLabel.A, pass_a), (PassLabel.B, pass_b)):
        while True:
            result = screen_next(project, actor, label)
            if result.batch is None:
                break
            items = [_verdict(label, result.batch.phase, record) for record in result.batch.records]
            screen_record(project, actor, result.batch.task_id, items)
        assert result.remaining == 0


def _verdict(label: PassLabel, phase: ScreeningPhase, record: dict[str, Any]) -> ScreeningItem:
    work_id, title = str(record["work_id"]), str(record["title"])
    parts = title.split()
    if (
        label is PassLabel.B
        and phase is ScreeningPhase.SCREENING
        and parts[0] == "Random"
        and int(parts[1]) % 4 == 0
    ):
        return ScreeningItem(
            work_id=work_id,
            verdict=Verdict.EXCLUDE,
            criterion="EX01",
            quote=title,
            rationale="off topic",
        )
    return ScreeningItem(
        work_id=work_id, verdict=Verdict.INCLUDE, criterion=None, quote=title, rationale="fits"
    )


def test_cli_resolve_and_audit_label(
    tmp_path: Path,
    settings: Settings,
    project: Project,
    clock: FixedClock,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
) -> None:
    _setup(project, agent, human, mock_sources, dual_sample=1.0)
    pass_b = Actor(
        kind="agent",
        id="screener-b",
        user="obd",
        session=S2,
        model="claude-haiku-5-5",
        skill=agent.skill,
    )
    env = _env(tmp_path)

    drawn = runner.invoke(app, ["calibrate", "draw"], env=env)
    assert drawn.exit_code == 0, drawn.stderr
    items = calibration_items(project)
    assert drawn.stdout.splitlines() == [f"calibration set: {len(items)} works", *sorted(items)]
    labelled = runner.invoke(
        app, ["calibrate", "label", items[0], "exclude", "--criterion", "EX01"], env=env
    )
    assert labelled.exit_code == 0, labelled.stderr
    for item in items[1:]:
        label_calibration(project, human, item, "include", None, Channel.CLI)
    _screen_passes(project, agent, pass_b)

    listing = runner.invoke(app, ["screen", "disagreements"], env=env)
    assert listing.exit_code == 0, listing.stderr
    disagreements = screen_agreement(project, human).disagreements
    assert disagreements, "the fixture must leave a disagreement"
    target = disagreements[0].work_id
    assert target in listing.stdout

    resolved = runner.invoke(
        app,
        ["screen", "resolve", target, "include", "--reason", "the abstract fits the question"],
        env=env,
    )
    assert resolved.exit_code == 0, resolved.stderr
    assert target not in runner.invoke(app, ["screen", "disagreements"], env=env).stdout
    bad = runner.invoke(app, ["screen", "resolve", target, "maybe", "--reason", "unclear"], env=env)
    assert bad.exit_code == 1 and "verdict:" in bad.stderr

    sampled = runner.invoke(app, ["audit", "sample"], env=env)
    assert sampled.exit_code == 0, sampled.stderr
    audit_id = re.search(r"aud_\w+", sampled.stdout)
    assert audit_id is not None
    [event] = _of_type(project, "audit.sampled")
    first_work = cast(list[str], event.payload["work_ids"])[0]
    labelled_audit = runner.invoke(
        app, ["audit", "label", audit_id.group(0), first_work, "include"], env=env
    )
    assert labelled_audit.exit_code == 0, labelled_audit.stderr
    unsampled = runner.invoke(
        app, ["audit", "label", audit_id.group(0), "W-not-sampled", "include"], env=env
    )
    assert unsampled.exit_code == 1 and "work_id:" in unsampled.stderr

    report = runner.invoke(app, ["audit", "report"], env=env)
    assert report.exit_code == 0, report.stderr
    assert f"audit {audit_id.group(0)}: sample" in report.stdout
    assert "labelled 1" in report.stdout
    item_lines = [ln for ln in report.stdout.splitlines() if " -> " in ln]
    assert len(item_lines) == len(cast(list[str], event.payload["work_ids"]))
    assert any(ln.startswith(f"{first_work}  ") and ln.endswith("-> include") for ln in item_lines)
    assert any("-> unlabelled" in ln for ln in item_lines)


def test_cli_seed_admit_requires_deviation_in_pilot(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    monkeypatch: Any,
) -> None:
    ready_protocol(project, agent, human, mock_sources)
    spec = SeedSpec(kind=SeedKind.POSITIVE, cite="Paper 7", doi="10.1000/p7")
    [outcome] = add_seeds(
        project,
        human,
        [spec],
        sources=mock_sources(),
        decision_ids=bind_ids(project, human, DecisionLevel.SEEDS),
    ).written
    explain_seed_miss(
        project, human, outcome.seed_id, "not indexed", ProvenanceMethod.SEED_ADMISSION
    )
    monkeypatch.setattr("factory.cli.main.default_sources", lambda: mock_sources())
    before = len(_of_type(project, "query.registered"))

    result = runner.invoke(app, ["seeds", "admit", outcome.seed_id], env=_cli_env(settings.root))

    assert result.exit_code == 1
    assert "deviation" in result.stderr
    assert len(_of_type(project, "query.registered")) == before
    assert _of_type(project, "seed.admitted") == []


# --- Full text (plan 2A, task 12): `factory fulltext …` ---


def _doi_of(project: Project, work_id: str) -> str:
    [work] = [w for w in list_works(project) if w.id == work_id]
    return work.identifiers.doi or ""


def _library_hash(project: Project, document_id: str) -> str:
    [added] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "fulltext.document_added" and e.refs[0] == document_id
    ]
    return str(added.payload["raw_hash"])


def test_cli_import_prints_report(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    tmp_path: Path,
) -> None:
    _build(project, agent, human, mock_sources)
    work = _promoted(project)[0]
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / f"{_doi_of(project, work).replace('/', '_')}.pdf", "Body text")
    _pdf(inbox / "unknown.pdf", "Nothing identifiable here")
    (inbox / "scan.pdf").write_bytes(b"not a pdf")

    result = runner.invoke(app, ["fulltext", "import", str(inbox)], env=_cli_env(settings.root))

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    for label, count in (
        ("imported", 1),
        ("already imported", 0),
        ("unmatched", 1),
        ("ambiguous", 0),
        ("not promoted", 0),
        ("not pdf", 1),
    ):
        assert f"{label}: {count}" in lines, result.stdout
    assert any(line.strip().startswith("unknown.pdf") for line in lines)
    assert any(line.strip().startswith("scan.pdf") for line in lines)


def test_cli_fetch_is_a_human_act(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(project, agent, human, mock_sources)
    work = _promoted(project)[0]
    stubs = _routes(html={work})
    monkeypatch.setattr("factory.cli.main.default_routes", lambda _settings: stubs)

    result = runner.invoke(
        app,
        ["fulltext", "fetch", "--work", work, "--route", "arxiv-html"],
        env=_cli_env(settings.root),
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("fetch fft_")
    assert stubs[Route.ARXIV_HTML].calls == [work]
    [started] = _of_type(project, "fulltext.fetch_started")
    assert started.actor.kind == "human"
    assert started.input_blob is None


def test_cli_fetch_rejects_researcher_route(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(project, agent, human, mock_sources)
    monkeypatch.setattr("factory.cli.main.default_routes", lambda _settings: _routes())

    result = runner.invoke(
        app,
        ["fulltext", "fetch", "--route", "researcher-supplied"],
        env=_cli_env(settings.root),
    )

    assert result.exit_code == 1
    assert "route.0: a researcher-supplied route is imported, not fetched" in result.stderr


def test_cli_status_prints_counts(
    project: Project, agent: Actor, human: Actor, mock_sources: Any, settings: Settings
) -> None:
    _build(project, agent, human, mock_sources)
    promoted = _promoted(project)
    fetch_fulltext(project, routes=_routes(html={promoted[0]}), work_ids=[promoted[0]])

    result = runner.invoke(app, ["fulltext", "status"], env=_cli_env(settings.root))

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == f"promoted: {len(promoted)}"
    assert "retrieved: 1" in lines and "not retrieved: 0" in lines


def test_cli_restore_missing(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(project, agent, human, mock_sources)
    work, other = _promoted(project)[0], _promoted(project)[1]
    fetched = fetch_fulltext(project, routes=_routes(html={work}), work_ids=[work])
    [document] = fetched.works[0].documents
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _pdf(inbox / f"{_doi_of(project, other).replace('/', '_')}.pdf", "Body text")
    [(_, _, supplied)] = import_folder(project, inbox).imported
    project.library.path(_library_hash(project, document)).unlink()
    project.library.path(_library_hash(project, supplied)).unlink()
    monkeypatch.setattr("factory.cli.main.default_routes", lambda _settings: _routes(html={work}))

    result = runner.invoke(app, ["fulltext", "restore", "--missing"], env=_cli_env(settings.root))

    assert result.exit_code == 0, result.stderr
    assert f"{document}  restored" in result.stdout.splitlines()
    assert f"{supplied}  needs-reimport" in result.stdout.splitlines()
    assert "1 needs-reimport, 1 restored" in result.stdout.splitlines()
    assert project.library.exists(_library_hash(project, document))
    assert not project.library.exists(_library_hash(project, supplied))


def test_cli_restore_unavailable_exits_nonzero(
    project: Project,
    agent: Actor,
    human: Actor,
    mock_sources: Any,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _build(project, agent, human, mock_sources)
    work = _promoted(project)[0]
    fetched = fetch_fulltext(project, routes=_routes(html={work}), work_ids=[work])
    [document] = fetched.works[0].documents
    project.library.path(_library_hash(project, document)).unlink()
    monkeypatch.setattr("factory.cli.main.default_routes", lambda _settings: _routes())

    result = runner.invoke(app, ["fulltext", "restore", document], env=_cli_env(settings.root))

    assert result.exit_code == 1
    assert result.stdout.splitlines() == [f"{document}  unavailable"]
    assert f"unavailable: {document}" in result.stderr

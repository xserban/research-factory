"""Slice-1 acceptance for the question, seeds, probe and protocol (criteria 6, 7, 13, 19, 22).

Agents act through the MCP tools over the real OpenAlex adapter on a mock transport, so nothing
here touches the network. Each test states the acceptance criterion it proves.
"""

import json
import re
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent
from typer.testing import CliRunner

from factory.cli.main import app
from factory.clock import FixedClock
from factory.config import Settings
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.mcp.server import build_server
from factory.model.search import QueryKind, QuerySpec
from factory.services import dedup as dedup_service
from factory.services import project as project_service
from factory.services.context import Project
from factory.services.protocol import (
    confirm_press,
    current_protocol,
    list_amendments,
    list_deviations,
    protocol_lineage,
)
from factory.services.question import current_question
from factory.services.seeds import SeedRole, all_seeds
from factory.sources.base import SearchResult, Source, SourceError
from factory.sources.registry import SourceFactory
from tests.helpers import (
    openalex_item,
    pilot_protocol_spec,
    pilot_question_spec,
    ready_protocol,
    record_pilot_question,
)

AGENT = {"role": "screener-a", "model": "claude-opus-5-5", "skill": "rf-screen"}
MockSources = Any


def _body(res: CallToolResult) -> dict[str, Any]:
    block = res.content[0]
    assert isinstance(block, TextContent)
    body: dict[str, Any] = json.loads(block.text)
    return body


async def _call(
    settings: Settings,
    clock: FixedClock,
    sources: dict[str, SourceFactory],
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    clock.advance(timedelta(milliseconds=1))
    server = build_server(settings, clock=clock, sources=sources)
    async with Client(server) as client:
        return _body(await client.call_tool(name, args))


def _item(n: int) -> dict[str, Any]:
    return openalex_item(
        title=f"Paper {n}",
        author="Ada Zhou",
        published="2020-01-01",
        openalex_id=f"W{n}",
        doi=f"10.1000/p{n}",
    )


def _seed(n: int, kind: str = "positive") -> dict[str, Any]:
    return {"kind": kind, "cite": f"Paper {n}", "doi": f"10.1000/p{n}"}


async def _add_seed(
    settings: Settings,
    clock: FixedClock,
    mock_sources: MockSources,
    n: int,
    kind: str = "positive",
) -> dict[str, Any]:
    """Add one seed through `seed_add`; its lookup resolves to the work for `n`."""
    body = await _call(
        settings,
        clock,
        dict(mock_sources(openalex=[_item(n)])),
        "seed_add",
        {"project": "demo", "seeds": [_seed(n, kind)], **AGENT},
    )
    assert body["ok"] is True and len(body["data"]["written"]) == 1, body
    return body


def _leaks(text: str, tokens: set[str]) -> list[str]:
    """Held-out tokens that appear in `text` as whole identifiers, case-insensitively."""
    return sorted(
        token
        for token in tokens
        if re.search(rf"(?<![0-9A-Za-z]){re.escape(token)}(?![0-9A-Za-z])", text, re.IGNORECASE)
    )


@pytest.mark.anyio
async def test_prose_only_change_mints_no_new_version_and_loosening_stales_exclusions(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
    human: Actor,
) -> None:
    # Acceptance 6: prose keeps the version; a loosened exclusion stales the decisions citing it.
    ready_protocol(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    versions_before = protocol_lineage(project)

    prose = current.spec.model_dump(mode="json")
    prose["rationale"] = "Reworded for clarity."
    prose["criteria"][0]["note"] = "A clarifying note."
    body = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {
            "project": "demo",
            "spec": prose,
            "reason": "Reword the rationale",
            "semantic": False,
            "effects": {},
            **AGENT,
        },
    )
    assert body["ok"] is True, body
    assert body["data"]["prose_only"] is True
    assert body["data"]["to_version"] == body["data"]["from_version"]
    assert body["data"]["stale_rules"] == []
    assert protocol_lineage(project) == versions_before

    loosened = current.spec.model_dump(mode="json")
    loosened["criteria"][1]["rule"] = "exclude topic 1 only in full-text studies"
    body = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {
            "project": "demo",
            "spec": loosened,
            "reason": "Narrow the exclusion",
            "semantic": True,
            "effects": {"EX01": "loosened"},
            **AGENT,
        },
    )
    assert body["ok"] is True, body
    assert body["data"]["prose_only"] is False
    assert {"criterion": "EX01", "stales": "exclusions-citing", "stage": "title-abstract"} in [
        {key: rule[key] for key in ("criterion", "stales", "stage")}
        for rule in body["data"]["stale_rules"]
    ]
    assert len(protocol_lineage(project)) == len(versions_before) + 1


@pytest.mark.anyio
async def test_probe_run_reports_recall_and_negative_hits_per_query_and_source(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
) -> None:
    # Acceptance 7: recall and negative hits are reported for each query and each source.
    record_pilot_question(project, agent)
    for n in (1, 2, 3):
        await _add_seed(settings, clock, mock_sources, n)
    await _add_seed(settings, clock, mock_sources, 9, kind="negative")

    everything = dict(mock_sources(openalex=[_item(n) for n in (1, 2, 3, 9)]))
    body = await _call(
        settings,
        clock,
        everything,
        "probe_run",
        {
            "project": "demo",
            "queries": [{"source": "openalex", "query": "attention"}],
            **AGENT,
        },
    )
    assert body["ok"] is True, body
    data = body["data"]
    [query] = data["queries"]
    assert query["source"] == "openalex" and query["status"] == "measured"
    assert query["recall"] == 1.0
    assert query["negatives_retrieved"] == ["NEG01"]
    assert data["per_source_recall"] == {"openalex": 1.0}
    assert data["pooled_recall"] == 1.0
    assert data["threshold"] == 0.9 and data["meets_threshold"] is True


@pytest.mark.anyio
async def test_parentless_criterion_is_rejected_and_nothing_written(
    settings: Settings, project: Project, clock: FixedClock, agent: Actor
) -> None:
    # Acceptance 13: a criterion with no parent is refused by its field path; nothing is written.
    question_id = record_pilot_question(project, agent)
    spec = pilot_protocol_spec(question_id, probe_id=None).model_dump(mode="json")
    spec["criteria"][0]["parent"] = None

    body = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": False, **AGENT},
    )
    assert body["ok"] is False
    assert "spec.criteria.0.parent" in [error["field"] for error in body["errors"]]
    assert "protocol.recorded" not in [
        e.type for e in read_all(project.paths.events_dir, project.catalog)
    ]
    assert current_protocol(project) is None


@pytest.mark.anyio
async def test_amendments_and_deviations_are_stored_separately(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
    human: Actor,
) -> None:
    # Acceptance 19: an amendment is a new protocol version; a deviation is a separate record.
    ready_protocol(project, agent, human, mock_sources)
    current = current_protocol(project)
    assert current is not None
    spec = current.spec.model_dump(mode="json")
    spec["criteria"][1]["rule"] = "exclude topic 1 only in full-text studies"
    amended = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {
            "project": "demo",
            "spec": spec,
            "reason": "Narrow the exclusion",
            "semantic": True,
            "effects": {"EX01": "loosened"},
            **AGENT,
        },
    )
    deviation = await _call(
        settings,
        clock,
        {},
        "protocol_deviation",
        {
            "project": "demo",
            "description": "Ran a citation chase outside the plan.",
            "reason": "A seed was missed by the planned query.",
            **AGENT,
        },
    )
    assert amended["ok"] is True and deviation["ok"] is True

    amendments = list_amendments(project)
    deviations = list_deviations(project)
    assert [a.amendment_id for a in amendments] == [amended["data"]["amendment_id"]]
    assert [d.deviation_id for d in deviations] == [deviation["data"]["deviation_id"]]
    types = [e.type for e in read_all(project.paths.events_dir, project.catalog)]
    assert types.count("protocol.amended") == 1
    assert types.count("protocol.deviation_recorded") == 1


@pytest.mark.anyio
async def test_agent_tools_never_reveal_held_out_seeds(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
    human: Actor,
) -> None:
    # Acceptance 22 (R-20): no agent-facing response carries a held-out seed id or identifier.
    question_id = record_pilot_question(project, agent)
    for n in (1, 2, 3):
        await _add_seed(settings, clock, mock_sources, n)
    await _add_seed(settings, clock, mock_sources, 9, kind="negative")

    responses: list[dict[str, Any]] = []
    probe = await _call(
        settings,
        clock,
        dict(mock_sources(openalex=[_item(n) for n in (1, 2, 3, 9)])),
        "probe_run",
        {"project": "demo", "queries": [{"source": "openalex", "query": "attention"}], **AGENT},
    )
    responses.append(probe)
    probe_id = probe["data"]["probe_id"]
    # Read after the probe, which draws the split: the held-out seed is then hidden.
    listed = await _call(settings, clock, {}, "seed_list", {"project": "demo"})
    responses.append(listed)

    held = [seed for seed in all_seeds(project) if seed.role is SeedRole.HELD_OUT]
    assert len(held) == 1, "the pilot split holds one of the three positives"
    tokens: set[str] = set()
    for seed in held:
        tokens.update(
            token
            for token in (seed.seed_id, seed.doi, seed.arxiv, seed.openalex, seed.work_id)
            if token
        )
        tokens.add(f"10.1000/p{seed.seed_id[-1]}")

    spec = pilot_protocol_spec(question_id, probe_id).model_dump(mode="json")
    draft = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": False, **AGENT},
    )
    responses.append(draft)
    review = await _call(
        settings,
        clock,
        {},
        "protocol_press_review",
        {
            "project": "demo",
            "protocol_id": draft["data"]["protocol_id"],
            "findings": [
                {"element": "text-words", "finding": "Add a synonym.", "severity": "minor"}
            ],
            **AGENT,
        },
    )
    responses.append(review)
    clock.advance(timedelta(milliseconds=1))  # the confirmation is not in the review's millisecond
    confirm_press(project, human, review["data"]["review_id"], ("Accepted.",))
    ready = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": True, **AGENT},
    )
    responses.append(ready)
    amended = await _call(
        settings,
        clock,
        {},
        "protocol_amend",
        {
            "project": "demo",
            "spec": {**spec, "rationale": "Reworded."},
            "reason": "Reword",
            "semantic": False,
            "effects": {},
            **AGENT,
        },
    )
    responses.append(amended)
    deviation = await _call(
        settings,
        clock,
        {},
        "protocol_deviation",
        {"project": "demo", "description": "A chase.", "reason": "A miss.", **AGENT},
    )
    responses.append(deviation)
    responses.append(await _call(settings, clock, {}, "project_status", {"project": "demo"}))
    # A seed that duplicates a held-out one is refused without naming it.
    duplicate = await _call(
        settings,
        clock,
        dict(mock_sources(openalex=[_item(1)])),
        "seed_add",
        {
            "project": "demo",
            "seeds": [{"kind": "positive", "cite": "Again", "doi": "10.1000/p1"}],
            **AGENT,
        },
    )
    responses.append(duplicate)
    responses.append(await _call(settings, clock, {}, "dedup_run", {"project": "demo", **AGENT}))
    responses.append(
        await _call(
            settings,
            clock,
            dict(mock_sources(openalex=[_item(n) for n in (1, 2, 3, 9)])),
            "search_run",
            {"project": "demo", "source": "openalex", "query": "attention", **AGENT},
        )
    )
    # A chase is refused by search_run; its refusal is scanned like every other response.
    refused_chase = await _call(
        settings,
        clock,
        {},
        "search_run",
        {
            "project": "demo",
            "source": "openalex",
            "query": "attention",
            "purpose": "chase",
            **AGENT,
        },
    )
    assert refused_chase["ok"] is False
    assert _leaks(json.dumps(refused_chase), tokens) == []

    assert all(response["ok"] is True for response in responses), responses
    for response in responses:
        assert _leaks(json.dumps(response), tokens) == []

    # Raw probe pages are human-only: no agent response carries a page's blob reference or the
    # keys of a raw OpenAlex record (final review, finding 2).
    archived: list[str] = [
        str(event.payload["raw_blob"])
        for event in read_all(project.paths.events_dir, project.catalog)
        if event.type == "probe.page_archived"
    ]
    assert archived, "the probe archived its raw pages"
    everything = json.dumps([*responses, refused_chase])
    for blob in archived:
        assert blob not in everything
    for raw_key in ('"display_name"', '"publication_date"', '"authorships"'):
        assert raw_key not in everything

    # Error payloads are scanned too (acceptance 22): a parentless criterion, and a worked
    # example that is held out, which must be refused with the same message as an unknown seed.
    held_id = next(seed.seed_id for seed in held)
    parentless = {
        **spec,
        "criteria": [{**spec["criteria"][0], "parent": None}, *spec["criteria"][1:]],
    }
    with_held = {
        **spec,
        "criteria": [
            spec["criteria"][0],
            {**spec["criteria"][1], "examples": {"include": [held_id], "exclude": []}},
            *spec["criteria"][2:],
        ],
    }
    with_unknown = {
        **spec,
        "criteria": [
            spec["criteria"][0],
            {**spec["criteria"][1], "examples": {"include": ["SEED99"], "exclude": []}},
            *spec["criteria"][2:],
        ],
    }
    refusals = [
        await _call(
            settings,
            clock,
            {},
            "protocol_record",
            {"project": "demo", "spec": candidate, "ready": False, **AGENT},
        )
        for candidate in (parentless, with_held, with_unknown)
    ]
    for refusal in refusals:
        assert refusal["ok"] is False, refusal
        assert _leaks(json.dumps(refusal), tokens) == []
    assert refusals[1]["errors"] == refusals[2]["errors"]
    assert "spec.criteria.0.parent" in [error["field"] for error in refusals[0]["errors"]]
    assert "rejected" not in json.dumps(refusals)  # no stray key in an error payload


@pytest.mark.anyio
async def test_question_to_gated_search_flow(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
) -> None:
    # Goal, question, seeds, probe, protocol draft, PRESS review, human confirmation over the CLI,
    # ready; then a planned search runs, an unplanned one is refused, and a deviation admits it.
    record_question_body = await _call(
        settings,
        clock,
        {},
        "question_record",
        {
            "project": "demo",
            "spec": pilot_question_spec().model_dump(mode="json"),
            "raw_goal": "Compare attention on vision",
            **AGENT,
        },
    )
    assert record_question_body["ok"] is True
    for n in (1, 2, 3):
        await _add_seed(settings, clock, mock_sources, n)

    probe = await _call(
        settings,
        clock,
        dict(mock_sources(openalex=[_item(1)])),
        "probe_run",
        {"project": "demo", "queries": [{"source": "openalex", "query": "attention"}], **AGENT},
    )
    assert probe["ok"] is True
    question = current_question(project)
    assert question is not None
    spec = pilot_protocol_spec(question.question_id, probe["data"]["probe_id"]).model_dump(
        mode="json"
    )

    draft = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": False, **AGENT},
    )
    assert draft["ok"] is True and draft["data"]["status"] == "draft"
    review = await _call(
        settings,
        clock,
        {},
        "protocol_press_review",
        {
            "project": "demo",
            "protocol_id": draft["data"]["protocol_id"],
            "findings": [
                {"element": "text-words", "finding": "Add a synonym.", "severity": "minor"}
            ],
            **AGENT,
        },
    )
    assert review["ok"] is True
    review_id = review["data"]["review_id"]

    runner = CliRunner()
    env = {"FACTORY_ROOT": str(settings.root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}
    confirmed = runner.invoke(
        app,
        ["--project", "demo", "protocol", "confirm-press", review_id, "--response", "Accepted."],
        env=env,
    )
    assert confirmed.exit_code == 0, confirmed.stderr

    ready = await _call(
        settings,
        clock,
        {},
        "protocol_record",
        {"project": "demo", "spec": spec, "ready": True, **AGENT},
    )
    assert ready["ok"] is True and ready["data"]["status"] == "ready"

    sources = dict(mock_sources(openalex=[_item(9)]))
    planned = await _call(
        settings,
        clock,
        sources,
        "search_run",
        {"project": "demo", "source": "openalex", "query": "attention", **AGENT},
    )
    assert planned["ok"] is True, planned

    unplanned = await _call(
        settings,
        clock,
        sources,
        "search_run",
        {"project": "demo", "source": "openalex", "query": "transformers", **AGENT},
    )
    assert unplanned["ok"] is False
    assert [error["field"] for error in unplanned["errors"]] == ["query"]

    deviation = await _call(
        settings,
        clock,
        {},
        "protocol_deviation",
        {
            "project": "demo",
            "description": "Search transformers as well.",
            "reason": "The planned query missed a known paper.",
            **AGENT,
        },
    )
    admitted = await _call(
        settings,
        clock,
        sources,
        "search_run",
        {
            "project": "demo",
            "source": "openalex",
            "query": "transformers",
            "deviation_id": deviation["data"]["deviation_id"],
            **AGENT,
        },
    )
    assert admitted["ok"] is True, admitted


@pytest.mark.anyio
async def test_protocol_rebuild_is_deterministic(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
    human: Actor,
) -> None:
    # The state hash after a rebuild from the event log equals the hash before the index is lost.
    ready_protocol(project, agent, human, mock_sources)
    runner = CliRunner()
    env = {"FACTORY_ROOT": str(settings.root), "FACTORY_USER": "obd", "FACTORY_PROJECT": None}
    first = runner.invoke(app, ["rebuild"], env=env)
    assert first.exit_code == 0

    index_dir = project.paths.dir / ".index"
    assert index_dir.exists()
    for path in index_dir.iterdir():
        path.unlink()
    index_dir.rmdir()
    second = runner.invoke(app, ["rebuild"], env=env)
    assert second.exit_code == 0
    assert second.stdout == first.stdout
    assert project.paths.index_path.exists()


class _Unreachable:
    """An OpenAlex stand-in whose every run fails with `message`, as a transport error would."""

    kinds = frozenset({QueryKind.KEYWORD})

    def __init__(self, message: str) -> None:
        self._message = message

    def run(self, spec: QuerySpec, **_kwargs: Any) -> SearchResult:
        raise SourceError(self._message)


@pytest.mark.anyio
async def test_search_run_and_dedup_run_outputs_are_scrubbed_of_held_out_identifiers(
    settings: Settings,
    project: Project,
    clock: FixedClock,
    mock_sources: MockSources,
    agent: Actor,
    human: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Final review, finding 2: search_run, dedup_run and project_status go through the same
    # scrubbing as every other tool, so a held-out identifier in their output is withheld.
    ready_protocol(project, agent, human, mock_sources)
    held = next(seed for seed in all_seeds(project) if seed.role is SeedRole.HELD_OUT)
    assert held.doi is not None
    failing = {
        "openalex": SourceFactory(
            frozenset({QueryKind.KEYWORD}),
            lambda _s, _c: cast(Source, _Unreachable(f"cannot reach {held.doi} today")),
        )
    }
    searched = await _call(
        settings,
        clock,
        failing,
        "search_run",
        {"project": "demo", "source": "openalex", "query": "attention", **AGENT},
    )
    assert searched["ok"] is True, searched
    assert held.doi not in json.dumps(searched)
    assert "[withheld]" in searched["data"]["note"]

    leaking = SimpleNamespace(model_dump=lambda mode: {"note": f"touched {held.doi}"})
    monkeypatch.setattr(dedup_service, "dedup_run", lambda _project: leaking)
    monkeypatch.setattr(project_service, "project_status", lambda _project: leaking)
    for name in ("dedup_run", "project_status"):
        body = await _call(settings, clock, {}, name, {"project": "demo", **AGENT})
        assert body["ok"] is True, body
        assert held.doi not in json.dumps(body)
        assert "[withheld]" in body["data"]["note"]

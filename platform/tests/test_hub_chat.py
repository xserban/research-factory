"""Hub chat page (spar night N5): the payload, the live read route, the four researcher write
routes and the basket entry points. Agent output is a proposal; the researcher rates and writes the
balance (ruling 8). No real `claude` is started: the runner start is replaced."""

# ruff: noqa: F811
from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from importlib import resources
from typing import Any

import pytest
from sqlalchemy import text

from factory.clock import FixedClock
from factory.config import Settings
from factory.errors import FactoryError, FactoryValidationError, ValidationIssue
from factory.events.envelope import Actor
from factory.events.reader import read_all
from factory.services import answers as an
from factory.services import chat_requests as cr
from factory.services import hub_build, hub_chat, hub_ui, site_server
from factory.services import runner as runner_service
from factory.services import sheets as sh
from factory.services.chat_candidates import CandidateInput as C
from factory.services.context import Project, list_projects
from factory.services.selection import SelectionSpec, resolve_selection_cached
from tests.extraction_helpers import (
    screened,  # noqa: F401
    world,  # noqa: F401
)

UI = "/p/demo/ui"
ANCHOR, QUOTE = "s3.p1", "Lorem ipsum"
SPEC = SelectionSpec()


# ---------------------------------------------------------------- helpers


def _arg(work: str, stance: str) -> sh.ArgumentInput:
    return sh.ArgumentInput(stance, work, ANCHOR, QUOTE, "it fails", "moderate")


def _sheet(project: Project, agent: Actor, world: list[str], *, close: bool = True) -> str:
    works = sorted(world)
    proposals = [
        C(works[0], "claims", "against", ANCHOR, QUOTE),
        C(works[1], "keyword", "for", ANCHOR, QUOTE),
    ]
    sheet = sh.open_sheet(project, agent, "Reflection helps", SPEC, proposals).sheet_id
    sh.record_arguments(project, agent, sheet, [_arg(works[0], "against")])
    if close:
        sh.close_section(project, agent, sheet, "against")
        sh.record_arguments(project, agent, sheet, [_arg(works[0], "for")])
        sh.close_section(project, agent, sheet, "for")
    return sheet


def _answer(project: Project, agent: Actor, world: list[str]) -> str:
    works = sorted(world)
    digest = resolve_selection_cached(project, SPEC).digest
    sentences = [an.SentenceInput("The paper says so.", works[0], ANCHOR, QUOTE)]
    return an.record_answer(project, agent, "Does it help?", SPEC, digest, sentences).answer_id


def _count(project: Project, etype: str) -> int:
    project.index.sync()
    with project.index.connect() as conn:
        return int(
            conn.execute(
                text("SELECT COUNT(*) FROM events WHERE type = :t"), {"t": etype}
            ).scalar_one()
        )


def _total(project: Project) -> int:
    return len(read_all(project.paths.events_dir, project.catalog))


# ---------------------------------------------------------------- the payload


def test_basket_resolves_works_with_titles_and_tokens(project: Project, world: list[str]) -> None:
    one = sorted(world)[0]
    spec = SelectionSpec(include=[one])
    b = hub_chat.basket_payload(project, spec)
    full = hub_chat.basket_payload(project, SPEC)
    assert full["count"] == len(world) and b["count"] == len(b["works"]) >= 1
    row = next(w for w in full["works"] if w["work_id"] == one)
    assert row["title"] and row["chars"] > 0 and row["est_tokens"] == row["chars"] // 4
    assert full["est_tokens"] == sum(w["est_tokens"] for w in full["works"]) or full["est_tokens"]
    assert len(full["digest"]) == 64 and set(full["spec"]) >= {"layers", "include", "exclude"}
    only = hub_chat.basket_payload(project, SelectionSpec(include=[one]), only=True)
    assert [w["work_id"] for w in only["works"]] == [one] and only["not_picked"] == len(world) - 1
    assert only["left_out"] == []
    out = hub_chat.basket_payload(project, SelectionSpec(exclude=[one]))
    assert one not in [w["work_id"] for w in out["works"]]
    assert [x["work_id"] for x in out["left_out"]] == [one]


def test_spec_parses_a_query_and_refuses_bad_input(project: Project) -> None:
    spec, only = hub_chat.parse_spec(
        {"layers": "core,applied", "include": "a, b", "exclude": "", "only": "1"}
    )
    assert (
        only
        and spec.layers == ["core", "applied"]
        and spec.include == ["a", "b"]
        and spec.exclude == []
    )
    with pytest.raises(FactoryValidationError):
        hub_chat.basket_payload(project, SelectionSpec(layers=["no-such-layer"]))


def test_chat_payload_lists_requests_by_state_and_earlier_results(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    empty = hub_chat.chat_payload(project)
    assert empty["ready"] and empty["requests"] == [] and empty["sheets"] == []
    sheet = _sheet(project, agent, world)
    ans = _answer(project, agent, world)
    r1 = cr.request_chat(project, human, "spar", SPEC, hypothesis="First").request_id
    r2 = cr.request_chat(project, human, "ask", SPEC, question="Second?").request_id
    p = hub_chat.chat_payload(project)
    assert [r["request_id"] for r in p["requests"]] == [r2, r1]  # newest first
    assert all(r["state"] == "open" and r["run"] is None for r in p["requests"])
    assert p["counts"]["open"] == 2 and p["counts"]["sheets"] == 1 and p["counts"]["answers"] == 1
    assert [s["sheet_id"] for s in p["sheets"]] == [sheet] and p["sheets"][0]["unrated"] == 2
    assert [a["answer_id"] for a in p["answers"]] == [ans]
    assert p["sheets"][0]["arguments"] == 2 and p["answers"][0]["sentences"] == 1


def test_sheet_view_has_balance_first_full_paragraph_and_computed_counts(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, world)
    v = hub_chat.sheet_view(project, sheet)
    keys = list(v)
    assert keys.index("balance") < keys.index("arguments")
    assert v["balance"]["recorded"] is False and v["balance"]["text"] == ""
    assert v["balance"]["writable"] is True and v["balance_label"]
    assert v["counts"]["arguments"] == 2 == len(v["arguments"]) and v["counts"]["unrated"] == 2
    a = v["arguments"][0]
    assert QUOTE in a["paragraph"] and a["paragraph"] != a["quote"] and a["title"]
    assert a["mark"] and a["paragraph"][a["mark"][0] : a["mark"][1]] == QUOTE
    assert a["rating"] is None and "linked_claim" in a
    arg_id = a["argument_id"]
    sh.rate_argument(project, human, arg_id, "weak", "thin")
    sh.record_balance(project, human, sheet, "Mixed evidence.", lean="mixed")
    w = hub_chat.sheet_view(project, sheet)
    assert w["balance"]["recorded"] and w["balance"]["text"] == "Mixed evidence."
    assert w["balance"]["lean"] == "mixed" and w["counts"]["unrated"] == 1
    assert next(x for x in w["arguments"] if x["argument_id"] == arg_id)["rating"] == "weak"


def test_balance_is_not_writable_while_a_section_is_open(
    project: Project, agent: Actor, world: list[str]
) -> None:
    sheet = _sheet(project, agent, world, close=False)
    assert hub_chat.sheet_view(project, sheet)["balance"]["writable"] is False


def test_answer_view_shows_each_paragraph_and_rating_state(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ans = _answer(project, agent, world)
    v = hub_chat.answer_view(project, ans)
    assert v["counts"]["sentences"] == 1 and v["counts"]["unrated"] == 1
    s = v["sentences"][0]
    assert QUOTE in s["paragraph"] and s["paragraph"] != s["quote"] and s["title"]
    assert s["rating"] is None
    an.rate_answer(project, human, ans, "sound", sentence=0)
    assert hub_chat.answer_view(project, ans)["sentences"][0]["rating"] == "sound"


def test_a_taken_request_shows_its_run_state(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    rid = cr.request_chat(project, human, "ask", SPEC, question="Q?").request_id
    fake = [{"run_id": "run_x", "status": "running", "exit_status": None}]
    monkeypatch.setattr(hub_chat, "_run_states", lambda p: {r["run_id"]: r for r in fake})
    monkeypatch.setattr(
        hub_chat,
        "_requests",
        lambda p: [
            cr.ChatRequestInfo(
                rid, "ask", None, "Q?", None, None, None, "taken", None, "run_x", "human", "t"
            )
        ],
    )
    got = hub_chat.chat_payload(project)["requests"][0]
    assert got["state"] == "taken" and got["run"]["status"] == "running"


def test_live_dispatches_and_refuses_unknown_ids(project: Project, world: list[str]) -> None:
    assert hub_chat.live(project, {})["ready"]
    assert hub_chat.live(project, {"basket": "1"})["count"] == len(world)
    with pytest.raises(FactoryValidationError):
        hub_chat.live(project, {"sheet": "sht_NOPE"})
    with pytest.raises(FactoryValidationError):
        hub_chat.live(project, {"answer": "not-an-id"})


# ---------------------------------------------------------------- the routes


def _req(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    sent = dict(headers or {})
    if body is not None:
        sent["Content-Type"] = "application/json"
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=sent)
    response = conn.getresponse()
    data = response.read()
    head = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, head, data


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int | None]]:
    """The runner start is replaced: nothing real is launched."""
    calls: list[tuple[str, int | None]] = []

    def fake(project: Project, stage: str, *, unit_cap: int | None = None, **kw: Any) -> str:
        calls.append((stage, unit_cap))
        return "run_fake"

    monkeypatch.setattr(runner_service, "start_run", fake)
    return calls


@pytest.fixture
def served(
    settings: Settings, clock: FixedClock, project: Project
) -> Iterator[tuple[int, Project]]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: project,  # one handle, as the real hub's slot: ids stay monotonic
        min_gap=300.0,
        background=False,
    )
    httpd: ThreadingHTTPServer = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], project
    httpd.shutdown()
    httpd.server_close()


def _token(port: int) -> str:
    page = _req(port, "GET", f"{UI}/chat.html")[2].decode()
    match = re.search(r"name='factory-token' content='([^']+)'", page)
    assert match is not None
    return match.group(1)


ROUTES = {
    "request": f"{UI}/act/chat-request",
    "argument": f"{UI}/act/chat-rate-argument",
    "sentence": f"{UI}/act/chat-rate-sentence",
    "balance": f"{UI}/act/chat-balance",
}


def test_the_page_and_the_live_route_are_served(
    served: tuple[int, Project], world: list[str]
) -> None:
    port, _ = served
    status, _, body = _req(port, "GET", f"{UI}/chat.html")
    assert status == 200 and "assets/pages/chat.js" in body.decode()
    assert _req(port, "GET", f"{UI}/assets/pages/chat.js")[0] == 200
    status, _, data = _req(port, "GET", f"{UI}/chat?basket=1&include={sorted(world)[0]}")
    assert status == 200 and json.loads(data)["count"] >= 1
    assert json.loads(_req(port, "GET", f"{UI}/chat")[2])["ready"] is True
    assert _req(port, "GET", f"{UI}/chat?sheet=sht_NOPE")[0] == 400
    assert "chat" in hub_ui.PAGES and "chat" in hub_build.BUILDERS


@pytest.mark.parametrize("name", list(ROUTES))
def test_every_write_route_needs_the_token_and_the_own_origin(
    served: tuple[int, Project], name: str
) -> None:
    port, project = served
    before = _total(project)
    body: dict[str, Any] = {"kind": "ask", "question": "Q?"}
    assert _req(port, "POST", ROUTES[name], body)[0] == 403
    assert _req(port, "POST", ROUTES[name], body, {"X-Factory-Token": "nope"})[0] == 403
    foreign = {"X-Factory-Token": _token(port), "Origin": "http://evil.example"}
    assert _req(port, "POST", ROUTES[name], body, foreign)[0] == 403
    assert _req(port, "PUT", ROUTES[name], body)[0] == 405
    assert _total(project) == before


def test_request_route_records_a_human_request_and_starts_the_run(
    served: tuple[int, Project], world: list[str], started: list[tuple[str, int | None]]
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    body = {
        "kind": "spar",
        "hypothesis": "Reflection helps",
        "mode": "prepare",
        "selection": {"layers": [], "include": [], "exclude": [sorted(world)[0]]},
    }
    status, _, data = _req(port, "POST", ROUTES["request"], body, auth)
    answer = json.loads(data)
    assert status == 200 and answer["ok"] and answer["request_id"].startswith("chr_")
    assert answer["run_id"] == "run_fake" and started == [("spar", None)]
    [event] = [
        e for e in read_all(project.paths.events_dir, project.catalog) if e.type == "chat.requested"
    ]
    assert event.actor.kind == "human" and event.payload["mode"] == "prepare"
    assert event.payload["selection"] == {
        "layers": [],
        "include": [],
        "exclude": [sorted(world)[0]],
        "population": "included-ft",
        "closed": False,
    }


def test_only_these_papers_is_recorded_closed_and_a_later_work_cannot_enter(
    project: Project, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    works = sorted(world)
    assert len(works) >= 2
    picked = works[:-1]
    real = hub_chat.population_works  # type: ignore[attr-defined]
    # the last work "joins the population later": it is missing when the order is placed
    with monkeypatch.context() as patch:
        patch.setattr(
            hub_chat, "population_works", lambda p, pop: [w for w in real(p, pop) if w != works[-1]]
        )
        body = {
            "kind": "ask",
            "question": "Q?",
            "start": False,
            "selection": {"only": True, "include": picked},
        }
        hub_chat.order_chat(project, human, body)
    [event] = [
        e for e in read_all(project.paths.events_dir, project.catalog) if e.type == "chat.requested"
    ]
    recorded = SelectionSpec.model_validate(event.payload["selection"])
    assert recorded.closed is True and recorded.include == picked and recorded.exclude == []
    resolved = resolve_selection_cached(project, recorded)
    assert [w.work_id for w in resolved.works] == picked


def test_request_route_keeps_the_request_when_the_run_cannot_start(
    served: tuple[int, Project],
    monkeypatch: pytest.MonkeyPatch,
    world: list[str],
) -> None:
    port, project = served

    def refuse(*a: Any, **k: Any) -> str:
        raise FactoryValidationError([ValidationIssue("run", "a run is open")])

    monkeypatch.setattr(runner_service, "start_run", refuse)
    auth = {"X-Factory-Token": _token(port)}
    status, _, data = _req(port, "POST", ROUTES["request"], {"kind": "ask", "question": "Q?"}, auth)
    answer = json.loads(data)
    assert status == 200 and answer["run_id"] is None and "a run is open" in answer["run_error"]
    assert answer["command"] == "factory queue process --stage ask"
    assert _count(project, "chat.requested") == 1


def test_request_route_without_start_only_records(
    served: tuple[int, Project],
    started: list[tuple[str, int | None]],
    world: list[str],
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    body = {"kind": "ask", "question": "Q?", "start": False}
    answer = json.loads(_req(port, "POST", ROUTES["request"], body, auth)[2])
    assert answer["ok"] and answer["run_id"] is None and started == []
    assert _count(project, "chat.requested") == 1


def test_request_route_refuses_bad_input_and_writes_nothing(
    served: tuple[int, Project], started: list[tuple[str, int | None]]
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    before = _total(project)
    for body in (
        {},
        {"kind": "talk"},
        {"kind": "spar"},
        {"kind": "spar", "hypothesis": "h", "question": "q"},
        {"kind": "ask", "question": "q", "mode": "prepare"},
        {"kind": "ask", "question": "q", "parent": "sht_NOPE"},
        {"kind": "ask", "question": "q", "selection": {"layers": ["no-such-layer"]}},
        {"kind": "ask", "question": "q", "selection": "all"},
        {"kind": "ask", "question": "q", "selection": {"include": "a"}},
        {"kind": "ask", "question": "q", "start": "yes"},
        {"kind": "ask", "question": "q" * 3000},
    ):
        status, _, data = _req(port, "POST", ROUTES["request"], body, auth)
        assert status == 400 and json.loads(data)["issues"], body
    assert _total(project) == before and started == []


def test_case_for_follow_up_goes_through_the_same_route(
    served: tuple[int, Project], agent: Actor, human: Actor, world: list[str],
    started: list[tuple[str, int | None]],
) -> None:  # fmt: skip
    port, project = served
    works = sorted(world)
    proposals = [C(works[0], "claims", "against", ANCHOR, QUOTE)]
    sheet = sh.open_sheet(project, agent, "H", SPEC, proposals, mode="prepare").sheet_id
    sh.record_arguments(project, agent, sheet, [_arg(works[0], "against")])
    sh.close_section(project, agent, sheet, "against")
    entry = hub_chat.chat_payload(project)["sheets"][0]
    assert entry["case_for_available"] is True
    auth = {"X-Factory-Token": _token(port)}
    body = {"kind": "spar", "hypothesis": "H", "mode": "prepare", "parent": sheet}
    answer = json.loads(_req(port, "POST", ROUTES["request"], body, auth)[2])
    assert answer["ok"] and started == [("spar", None)]
    assert hub_chat.chat_payload(project)["sheets"][0]["case_for_available"] is False


def test_rate_argument_route_writes_a_human_rating_and_refuses_bad_input(
    served: tuple[int, Project], agent: Actor, world: list[str]
) -> None:
    port, project = served
    sheet = _sheet(project, agent, world)
    arg = hub_chat.sheet_view(project, sheet)["arguments"][0]["argument_id"]
    auth = {"X-Factory-Token": _token(port)}
    before = _total(project)
    for body in (
        {},
        {"argument_id": arg},
        {"argument_id": arg, "rating": "great"},
        {"argument_id": "arg_NOPE", "rating": "sound"},
        {"argument_id": arg, "rating": "sound", "note": "n" * 5000},
        {"argument_id": 5, "rating": "sound"},
        {"argument_id": arg, "rating": "sound", "note": 3},
    ):
        status, _, data = _req(port, "POST", ROUTES["argument"], body, auth)
        assert status == 400 and json.loads(data)["issues"], body
    assert _total(project) == before
    ok = {"argument_id": arg, "rating": "wrong", "note": "misread"}
    status, _, data = _req(port, "POST", ROUTES["argument"], ok, auth)
    assert status == 200 and json.loads(data)["ok"]
    [event] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "sheet.argument_rated"
    ]
    assert event.actor.kind == "human" and event.payload["rating"] == "wrong"


def test_a_write_through_the_hub_is_read_back_at_once_under_a_frozen_clock(
    served: tuple[int, Project], agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flake root cause: with a frozen clock two Project handles mint ids in the same millisecond
    from their own random starts, so the hub's rating could sort BEFORE the sheet events the test
    handle wrote earlier, and the projection ignored it. Worst case forced here: random bits 0."""

    import secrets

    monkeypatch.setattr(secrets, "randbits", lambda n: 0)
    port, project = served
    sheet = _sheet(project, agent, world)
    arg = hub_chat.sheet_view(project, sheet)["arguments"][0]["argument_id"]
    auth = {"X-Factory-Token": _token(port)}
    body = {"argument_id": arg, "rating": "weak", "note": "n"}
    assert _req(port, "POST", ROUTES["argument"], body, auth)[0] == 200
    assert hub_chat.sheet_view(project, sheet)["arguments"][0]["rating"] == "weak"


def test_rate_sentence_route_rates_a_sentence_or_the_whole_answer(
    served: tuple[int, Project], agent: Actor, world: list[str]
) -> None:
    port, project = served
    ans = _answer(project, agent, world)
    auth = {"X-Factory-Token": _token(port)}
    before = _total(project)
    for body in (
        {},
        {"answer_id": ans},
        {"answer_id": ans, "rating": "sound", "sentence": 9},
        {"answer_id": ans, "rating": "sound", "sentence": "0"},
        {"answer_id": ans, "rating": "sound", "sentence": True},
        {"answer_id": "ans_NOPE", "rating": "sound"},
    ):
        status, _, data = _req(port, "POST", ROUTES["sentence"], body, auth)
        assert status == 400 and json.loads(data)["issues"], body
    assert _total(project) == before
    for body in (
        {"answer_id": ans, "rating": "weak", "sentence": 0, "note": "thin"},
        {"answer_id": ans, "rating": "sound"},
    ):
        assert _req(port, "POST", ROUTES["sentence"], body, auth)[0] == 200
    events = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "chat.answer_rated"
    ]
    assert len(events) == 2 and {e.actor.kind for e in events} == {"human"}
    view = hub_chat.answer_view(project, ans)
    assert view["sentences"][0]["rating"] == "weak" and view["rating"] == "sound"


def test_balance_route_writes_the_researchers_text_and_refuses_bad_input(
    served: tuple[int, Project], agent: Actor, world: list[str]
) -> None:
    port, project = served
    closed = _sheet(project, agent, world)
    open_ = _sheet(project, agent, world, close=False)
    auth = {"X-Factory-Token": _token(port)}
    before = _total(project)
    for body in (
        {},
        {"sheet_id": closed},
        {"sheet_id": closed, "text": "  "},
        {"sheet_id": closed, "text": "x", "lean": "yes"},
        {"sheet_id": open_, "text": "too early"},
        {"sheet_id": "sht_NOPE", "text": "x"},
        {"sheet_id": closed, "text": "x" * 5000},
        {"sheet_id": closed, "text": "x", "note": 3},
    ):
        status, _, data = _req(port, "POST", ROUTES["balance"], body, auth)
        assert status == 400 and json.loads(data)["issues"], body
    assert _total(project) == before
    ok = {"sheet_id": closed, "text": "The evidence is mixed.", "lean": "mixed", "note": "n"}
    assert _req(port, "POST", ROUTES["balance"], ok, auth)[0] == 200
    [event] = [
        e
        for e in read_all(project.paths.events_dir, project.catalog)
        if e.type == "sheet.balance_recorded"
    ]
    assert event.actor.kind == "human" and event.payload["lean"] == "mixed"
    assert hub_chat.sheet_view(project, closed)["balance"]["text"] == "The evidence is mixed."


# ---------------------------------------------------------------- the page script


def _js(name: str) -> str:
    return resources.files("factory.hub_ui").joinpath(name).read_text(encoding="utf-8")


def test_the_chat_page_is_registered_in_the_rail_and_the_palette() -> None:
    spec = hub_ui.PAGES["chat"]
    assert spec.script == "pages/chat.js" and "chat" in spec.payloads
    assert "pages/chat.js" in hub_ui.ASSETS
    shell = _js("shell.js")
    block = re.search(r"const RAIL = \[(.*?)\n\];", shell, flags=re.S)
    assert block and "['chat'," in block.group(1)
    assert "'chat.html'" in shell and re.search(r"\bchat:'<path", shell)
    assert "HUB.chatHref" in shell


def test_the_chat_script_escapes_everything_it_renders() -> None:
    src = _js("pages/chat.js")
    assert "const { esc" in src or "H.esc" in src
    fields = "quote|paragraph|claim|title|note|text|hypothesis|question|reason|about"
    stripped = src
    for _ in range(3):  # every esc(...) call, with up to two nested parentheses, is safe text
        stripped = re.sub(r"esc\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)", "ESC", stripped)
    bare = re.findall(
        rf"(?<![\w.])\b(?:a|s|r|x|w|v|b|c|req|sh|an|arg|sent|run)\.(?:{fields})\b(?!\s*[?&|=!])",
        stripped,
    )
    assert not bare, bare
    assert "esc(a.quote)" in src and "esc(p.slice" in src
    # the payload text is never put in the page as markup through a raw assignment
    assert "outerHTML" not in src and "document.write" not in src
    assert "insertAdjacentHTML" not in src or "esc(" in src


def test_the_chat_script_uses_the_allow_listed_routes_and_hash_state() -> None:
    src = _js("pages/chat.js")
    for route in ("chat-request", "chat-rate-argument", "chat-rate-sentence", "chat-balance"):
        assert f"/ui/act/{route}" in src
    assert "H.hash" in src and "HUB.served" in src
    for word in ("Explore", "Prepare", "Spar", "Ask", "case for", "sound", "weak", "wrong"):
        assert word.lower() in src.lower()


def test_entry_points_link_to_the_chat_hash() -> None:
    shell = _js("shell.js")
    assert "chat.html#" in shell
    corpus = _js("pages/corpus.js")
    assert "HUB.chatHref" in corpus
    for label in ("Add to chat", "Chat with these", "whole layer", "Spar with this paper"):
        assert label.lower() in corpus.lower() or label.lower() in shell.lower(), label
    assert "Spar with this paper" in shell
    contra = _js("pages/contradictions.js")
    assert "Spar this pair" in contra and "HUB.chatHref" in contra and "seed" in contra


# ---------------------------------------------------------------- review fixes


def test_the_marked_span_is_escaped_in_the_rendered_paragraph() -> None:
    """Run chat.js `paragraph()` itself (node) on a long paragraph whose marked quote holds markup;
    the static check pins the three escaped pieces when node is absent."""
    import shutil
    import subprocess

    src = _js("pages/chat.js")
    body = re.search(r"function paragraph\(a\) \{.*?\n  \}\n", src, flags=re.S)
    assert body is not None
    fn = body.group(0)
    assert fn.count("esc(") >= 4 and "<mark>${esc(p.slice(m[0], m[1]))}</mark>" in fn
    node = shutil.which("node")
    if node is None:
        return
    quote = "<img src=x onerror=alert(1)>"
    para = "A long enough paragraph of more than forty characters, with " + quote + " inside it."
    start = para.index(quote)
    script = (
        "const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')"
        ".replace(/>/g,'&gt;').replace(/\"/g,'&quot;');\n"
        + fn
        + f"\nconsole.log(paragraph({{paragraph: {json.dumps(para)}, "
        f"mark: [{start}, {start + len(quote)}]}}));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    assert "<img" not in out and "&lt;img src=x onerror=alert(1)&gt;" in out
    assert out.count("<mark>") == 1 and len(para) > 40


def test_a_view_carries_the_whole_paragraph_not_a_clip(
    project: Project, agent: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    sheet = _sheet(project, agent, world)
    full = "Before the quote, a long opening sentence. Lorem ipsum dolor sit amet. And a tail."
    assert len(full) > 40
    manifest = SimpleNamespace(get=lambda anchor: SimpleNamespace(text=full))
    monkeypatch.setattr(hub_chat, "conversion_manifest", lambda p, c: manifest)
    shown = hub_chat.sheet_view(project, sheet)["arguments"][0]
    assert shown["paragraph"] == full
    start, end = shown["mark"]
    assert shown["paragraph"][start:end] == QUOTE


BODIES: dict[str, dict[str, Any]] = {
    "request": {"kind": "ask", "question": "Q?", "start": False},
    "argument": {"argument_id": "arg_X", "rating": "sound"},
    "sentence": {"answer_id": "ans_X", "rating": "sound"},
    "balance": {"sheet_id": "sht_X", "text": "t"},
}


@pytest.mark.parametrize("name", list(ROUTES))
def test_a_principal_without_the_human_act_permission_is_refused_on_every_route(
    served: tuple[int, Project], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    port, project = served
    asked: list[str] = []

    def refuse(*a: Any, **k: Any) -> None:
        asked.append(str(a[2]))
        raise FactoryError("permission: human-act:confirm not held")

    monkeypatch.setattr(site_server, "authorize_command", refuse)
    before = _total(project)
    auth = {"X-Factory-Token": _token(port)}
    status, _, data = _req(port, "POST", ROUTES[name], BODIES[name], auth)
    assert status == 403 and json.loads(data)["issues"]
    assert _total(project) == before and len(asked) == 1 and asked[0].startswith("cli:")


def test_an_unknown_kind_is_refused_before_any_access_row_is_chosen(
    served: tuple[int, Project],
    monkeypatch: pytest.MonkeyPatch,
    world: list[str],
) -> None:
    port, _ = served
    asked: list[str] = []
    monkeypatch.setattr(site_server, "authorize_command", lambda *a, **k: asked.append(str(a[2])))
    auth = {"X-Factory-Token": _token(port)}
    body = {"kind": "talk", "question": "Q?"}
    assert _req(port, "POST", ROUTES["request"], body, auth)[0] == 400
    assert asked == []
    assert _req(port, "POST", ROUTES["request"], {"kind": "ask", "question": "Q"}, auth)[0] == 200
    assert asked == ["cli:chat request ask"]


def test_a_failing_run_start_keeps_the_request_and_answers_run_error(
    served: tuple[int, Project],
    monkeypatch: pytest.MonkeyPatch,
    world: list[str],
) -> None:
    port, project = served

    def boom(*a: Any, **k: Any) -> str:
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(runner_service, "start_run", boom)
    auth = {"X-Factory-Token": _token(port)}
    status, _, data = _req(
        port, "POST", ROUTES["request"], BODIES["request"] | {"start": True}, auth
    )
    answer = json.loads(data)
    assert status == 200 and answer["run_id"] is None and "spawn failed" in answer["run_error"]
    assert answer["command"] == "factory queue process --stage ask"
    assert _count(project, "chat.requested") == 1


def test_a_double_click_does_not_record_the_same_order_twice(
    served: tuple[int, Project],
    started: list[tuple[str, int | None]],
    world: list[str],
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    body = {"kind": "ask", "question": "Q?", "start": False}
    assert _req(port, "POST", ROUTES["request"], body, auth)[0] == 200
    status, _, data = _req(port, "POST", ROUTES["request"], body, auth)
    assert status == 400 and json.loads(data)["issues"][0]["field"] == "request"
    assert _count(project, "chat.requested") == 1
    other = dict(body, question="Another?")
    assert _req(port, "POST", ROUTES["request"], other, auth)[0] == 200
    narrower = dict(body, selection={"only": True, "include": [sorted(project_works(project))[0]]})
    assert _req(port, "POST", ROUTES["request"], narrower, auth)[0] == 200
    assert _count(project, "chat.requested") == 3


def project_works(project: Project) -> list[str]:
    return [w.work_id for w in resolve_selection_cached(project, SPEC).works]


def test_the_order_button_is_disabled_while_the_post_is_in_flight() -> None:
    src = _js("pages/chat.js")
    assert "go.disabled = true" in src and "go.disabled = false" in src
    assert "st.size = ok ? j.count : null" in src
    assert "document.activeElement &&" in src


def test_an_order_whose_selection_resolves_to_no_works_is_refused(
    served: tuple[int, Project], started: list[tuple[str, int | None]], world: list[str]
) -> None:
    port, project = served
    auth = {"X-Factory-Token": _token(port)}
    before = _total(project)
    for selection in (
        {"only": True, "include": []},
        {"closed": True, "include": []},
        {"exclude": sorted(world)},
    ):
        body = {"kind": "ask", "question": "Q?", "selection": selection}
        status, _, data = _req(port, "POST", ROUTES["request"], body, auth)
        assert status == 400, selection
        assert json.loads(data)["issues"][0]["field"] == "selection"
    assert _total(project) == before and started == []


def test_the_chat_payload_is_cached_on_the_event_log_signature(
    project: Project, agent: Actor, human: Actor, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _sheet(project, agent, world)
    calls: list[str] = []
    real = sh.view_sheet

    def counting(p: Project, sheet_id: str) -> Any:
        calls.append(sheet_id)
        return real(p, sheet_id)

    monkeypatch.setattr(sh, "view_sheet", counting)
    first = hub_chat.chat_payload(project)
    n = len(calls)
    assert n >= 1
    assert hub_chat.chat_payload(project) == first and len(calls) == n
    cr.request_chat(project, human, "ask", SPEC, question="Q?")
    again = hub_chat.chat_payload(project)
    assert len(again["requests"]) == 1 and len(calls) > n


def test_the_basket_uses_the_cached_resolution(
    project: Project, world: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import selection as selection_module

    calls: list[int] = []
    real = selection_module.resolve_selection

    def counting(p: Project, spec: SelectionSpec) -> Any:
        calls.append(1)
        return real(p, spec)

    monkeypatch.setattr(selection_module, "resolve_selection", counting)
    spec = SelectionSpec(include=[sorted(world)[0]])
    hub_chat.basket_payload(project, spec)
    hub_chat.basket_payload(project, spec)
    assert len(calls) == 1


# ---------------------------------------------------------------- threads, batches, context


def _row(rid: str, parent: str | None, state: str, result: str | None, ts: str) -> dict[str, Any]:
    return {
        "request_id": rid,
        "kind": "ask",
        "hypothesis": None,
        "question": f"q {rid}",
        "mode": None,
        "parent": parent,
        "state": state,
        "result": result,
        "ts": ts,
    }


def _ans(aid: str, parent: str | None, ts: str) -> dict[str, Any]:
    return {"answer_id": aid, "question": f"a {aid}", "sentences": 1, "parent": parent, "ts": ts}


def test_threads_are_derived_from_parent_links_only() -> None:
    answers = [_ans("ans_1", None, "t1"), _ans("ans_2", "ans_1", "t3"), _ans("ans_9", None, "t9")]
    sheets = [
        {"sheet_id": "sht_1", "hypothesis": "h", "mode": "explore", "respar_of": None, "ts": "t4"}
    ]
    requests = [
        _row("chr_1", None, "done", "ans_1", "t0"),
        _row("chr_2", "ans_1", "done", "ans_2", "t2"),
        _row("chr_3", "ans_1", "done", "sht_1", "t3b"),  # a spar over the answer's question
        _row("chr_4", "ans_2", "open", None, "t5"),  # waiting follow-up, no result yet
        _row("chr_5", "sht_1", "taken", None, "t6"),
        _row("chr_6", "ghost", "open", None, "t7"),  # unknown parent: a root of its own
    ]
    got = hub_chat.threads(requests, sheets, answers)
    by_root = {t["root"]: t for t in got}
    one = by_root["ans_1"]
    assert [(n["id"], n["depth"]) for n in one["nodes"]] == [
        ("ans_1", 0),
        ("ans_2", 1),
        ("chr_4", 2),
        ("sht_1", 1),
        ("chr_5", 2),
    ]
    assert one["count"] == 5 and one["latest"] == "t6" and one["state"] == "taken"
    assert by_root["ans_9"]["state"] == "answered" and by_root["ans_9"]["count"] == 1
    assert by_root["chr_6"]["state"] == "open" and by_root["chr_6"]["nodes"][0]["type"] == "request"
    assert [t["root"] for t in got] == ["ans_9", "chr_6", "ans_1"]
    assert got == hub_chat.threads(requests, sheets, answers)  # deterministic


def test_a_cycle_of_parents_makes_roots_not_a_loop() -> None:
    answers = [_ans("ans_1", "ans_2", "t1"), _ans("ans_2", "ans_1", "t2")]
    got = hub_chat.threads([], [], answers)
    assert sorted(t["root"] for t in got) == ["ans_1", "ans_2"]


def test_the_payload_carries_threads_from_real_follow_ups(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ans = _answer(project, agent, world)
    follow = cr.request_chat(project, human, "ask", SPEC, question="Why?", parent=ans).request_id
    p = hub_chat.chat_payload(project)
    thread = p["threads"][0]
    assert [n["id"] for n in thread["nodes"]] == [ans, follow]
    assert thread["nodes"][1]["state"] == "open" and thread["state"] == "open"
    assert p["batch_max"] == hub_chat.BATCH_MAX


def test_context_view_gives_the_selection_and_cited_works(
    project: Project, agent: Actor, world: list[str]
) -> None:
    ans = _answer(project, agent, world)
    sheet = _sheet(project, agent, world)
    got = hub_chat.live(project, {"context": ans})
    assert got["works"] == [sorted(world)[0]] and "layers" in got["selection"]
    assert hub_chat.live(project, {"context": sheet})["works"] == [sorted(world)[0]]
    with pytest.raises(FactoryValidationError):
        hub_chat.live(project, {"context": "sht_NOPE"})


def test_a_batch_records_every_line_in_order_and_starts_one_run(
    project: Project, human: Actor, world: list[str], started: list[tuple[str, int | None]]
) -> None:
    got = hub_chat.order_chat_batch(
        project, human, {"kind": "ask", "lines": ["One?", "", "  Two?  ", "Three?"]}
    )
    ids = got["request_ids"]
    assert isinstance(ids, list) and len(ids) == 3 and got["run_id"] == "run_fake"
    assert started == [("ask", None)]
    rows = {r.request_id: r for r in cr.list_requests(project)}
    assert [rows[i].question for i in ids] == ["One?", "Two?", "Three?"]


def test_a_batch_with_a_bad_line_writes_nothing(
    project: Project, human: Actor, world: list[str], started: list[tuple[str, int | None]]
) -> None:
    before = _total(project)
    bad: list[dict[str, Any]] = [
        {"kind": "ask", "lines": ["ok?", "x" * 3000]},
        {"kind": "ask", "lines": ["same?", "SAME?"]},
        {"kind": "ask", "lines": []},
        {"kind": "ask", "lines": ["  ", ""]},
        {"kind": "ask", "lines": "one"},
        {"kind": "ask", "lines": ["ok?"], "parent": "sht_NOPE"},
        {"kind": "ask", "lines": ["ok?"], "mode": "prepare"},
        {"kind": "ask", "lines": ["ok?"], "note": "n" * 700},
        {"kind": "ask", "lines": ["ok?"], "selection": {"layers": ["no-such-layer"]}},
        {"kind": "talk", "lines": ["ok?"]},
        {"lines": ["ok?"]},
    ]
    for body in bad:
        with pytest.raises(FactoryValidationError):
            hub_chat.order_chat_batch(project, human, body)
    assert _total(project) == before and started == []
    with pytest.raises(FactoryValidationError) as exc:
        hub_chat.order_chat_batch(project, human, {"kind": "ask", "lines": ["ok?", "x" * 3000]})
    assert [i.field for i in exc.value.issues] == ["lines[1]"]


def test_a_batch_is_capped_and_refuses_an_order_already_waiting(
    project: Project, human: Actor, world: list[str], started: list[tuple[str, int | None]]
) -> None:
    many = [f"Question {i}?" for i in range(hub_chat.BATCH_MAX + 1)]
    with pytest.raises(FactoryValidationError) as exc:
        hub_chat.order_chat_batch(project, human, {"kind": "ask", "lines": many})
    assert "at most 10" in exc.value.issues[0].reason
    ok = hub_chat.order_chat_batch(
        project, human, {"kind": "ask", "lines": many[:10], "start": False}
    )
    assert len(ok["request_ids"]) == 10 and started == []  # type: ignore[arg-type]
    before = _total(project)
    with pytest.raises(FactoryValidationError) as dup:
        hub_chat.order_chat_batch(project, human, {"kind": "ask", "lines": ["new?", many[3]]})
    assert dup.value.issues[0].field == "lines[1]" and _total(project) == before


def test_a_batch_follow_up_shares_the_parent_and_the_selection(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    ans = _answer(project, agent, world)
    got = hub_chat.order_chat_batch(
        project,
        human,
        {"kind": "ask", "lines": ["A?", "B?"], "parent": ans, "start": False, "note": "n"},
    )
    rows = {r.request_id: r for r in cr.list_requests(project)}
    assert [rows[i].parent for i in got["request_ids"]] == [ans, ans]  # type: ignore[union-attr]
    assert all(r.note == "n" for r in rows.values())


def test_a_case_for_batch_is_one_line_only(
    project: Project, agent: Actor, human: Actor, world: list[str]
) -> None:
    works = sorted(world)
    sheet = sh.open_sheet(
        project, agent, "H", SPEC, [C(works[0], "claims", "against", ANCHOR, QUOTE)], mode="prepare"
    ).sheet_id
    sh.record_arguments(project, agent, sheet, [_arg(works[0], "against")])
    sh.close_section(project, agent, sheet, "against")
    body = {"kind": "spar", "mode": "prepare", "parent": sheet, "start": False}
    with pytest.raises(FactoryValidationError):
        hub_chat.order_chat_batch(project, human, {**body, "lines": ["H", "H2"]})
    assert (
        len(hub_chat.order_chat_batch(project, human, {**body, "lines": ["H"]})["request_ids"]) == 1
    )  # type: ignore[arg-type]


def test_the_batch_route_needs_the_token_and_records_the_lines(
    served: tuple[int, Project], world: list[str], started: list[tuple[str, int | None]]
) -> None:
    port, project = served
    route = f"{UI}/act/chat-batch"
    body = {"kind": "ask", "lines": ["One?", "Two?"]}
    assert _req(port, "POST", route, body)[0] in (401, 403)
    before = _total(project)
    status, _, data = _req(port, "POST", route, body, {"X-Factory-Token": _token(port)})
    assert status == 200 and len(json.loads(data)["request_ids"]) == 2
    assert _total(project) > before and started == [("ask", None)]


def test_the_chat_script_has_the_conversation_controls() -> None:
    src = _js("pages/chat.js")
    assert "/ui/act/chat-batch" in src
    for word in (
        "Follow up",
        "Following up on:",
        "Same papers as the parent",
        "Spar this claim",
        "Ask about this",
        "Already read in the parent:",
        "waiting for a session",
        "Saved",
    ):
        assert word in src, word
    assert "parent: " in src and "context=" in src

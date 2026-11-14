"""The hub feed page `/feed/` and its two acts (plan 2026-11-13-hub-feed, part 4): a tab per
project, the cards of each project's latest ranking, a status line, Fetch now and Refetch.

No network: the runner gets a scripted function, the events are recorded directly."""

from __future__ import annotations

import http.client
import json
import re
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.events.reader import read_all
from factory.services import site_hub_feed, site_server
from factory.services.context import Project, list_projects, open_project
from factory.services.feed import FeedRunAll
from factory.services.project import init_project
from tests.helpers import SESSION
from tests.test_feed_index import RANKING
from tests.test_feed_read import FIRST, HELD, SECOND
from tests.test_site_feed import _world, stub_titles  # noqa: F401  (fixture)


def _req(
    port: int, method: str, path: str, body: object | None = None, token: str | None = None
) -> tuple[int, str]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Factory-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    response = conn.getresponse()
    text = response.read().decode(errors="replace")
    conn.close()
    return response.status, text


def _meta_token(page: str) -> str:
    match = re.search(r"name='factory-token' content='([^']+)'", page)
    assert match is not None
    return match.group(1)


class Scripted:
    """A feed run that records its calls and can be held open."""

    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.release = threading.Event()
        self.hold = False

    def __call__(self, refetch: bool) -> FeedRunAll:
        self.calls.append(refetch)
        if self.hold:
            assert self.release.wait(10)
        return FeedRunAll(exit_code=0, outcomes=())


@pytest.fixture
def two(settings: Settings, clock: FixedClock, project: Project) -> Project:
    return init_project(settings, "other", "pilot", session=SESSION, clock=clock)


@pytest.fixture
def script() -> Scripted:
    return Scripted()


def _serve(
    settings: Settings, clock: FixedClock, runner: site_server.FeedRunner | None
) -> tuple[ThreadingHTTPServer, site_server.MainHub]:
    hub = site_server.MainHub(
        settings.root,
        lambda: list_projects(settings),
        lambda slug: open_project(settings, slug, session=SESSION, clock=clock),
        min_gap=300.0,
        background=False,
        feed=runner,
    )
    httpd = site_server.make_main_server(hub, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, hub


@pytest.fixture
def served(
    settings: Settings, clock: FixedClock, two: Project, script: Scripted
) -> Iterator[tuple[int, site_server.MainHub, Scripted]]:
    httpd, hub = _serve(settings, clock, site_server.FeedRunner(script))
    yield httpd.server_address[1], hub, script
    script.release.set()
    httpd.shutdown()
    httpd.server_close()


def test_without_feed_events_every_project_is_a_tab_marked_not_configured(
    served: tuple[int, site_server.MainHub, Scripted],
) -> None:
    port, _, _ = served
    status, page = _req(port, "GET", "/feed/")
    assert status == 200
    assert "data-slug='demo'" in page and "data-slug='other'" in page
    assert page.count("not configured") >= 2
    assert "<article" not in page
    assert "no run yet" in page


def test_the_cards_show_the_ranking_of_the_tabs_project_and_never_a_held_entry(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    port, _, _ = served
    _world(project)
    page = _req(port, "GET", "/feed/")[1]
    demo = page.split("<section class=pn data-slug='demo'", 1)[1].split("<section", 1)[0]
    assert f"https://arxiv.org/abs/{FIRST}" in demo and f"https://arxiv.org/pdf/{FIRST}" in demo
    assert "0.900" in demo and "A core reference" in demo
    assert HELD not in page
    other = page.split("<section class=pn data-slug='other'", 1)[1]
    assert FIRST not in other
    assert "last fetch" in demo and "2026-11-11" in demo
    assert "references: core" in demo and "1 reference" in demo


def test_the_page_has_a_token_per_tab_and_one_for_the_hub_acts(
    served: tuple[int, site_server.MainHub, Scripted], project: Project, two: Project
) -> None:
    port, _, _ = served
    page = _req(port, "GET", "/feed/")[1]
    tokens = re.findall(r"data-slug='(\w+)' data-token='([0-9a-f]+)'", page)
    assert {s for s, _ in tokens} == {"demo", "other"}
    assert len({t for _, t in tokens} | {_meta_token(page)}) == 3


def test_a_reaction_from_a_tab_is_recorded_for_that_project_as_the_human(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    two: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    port, _, _ = served
    _world(project)
    page = _req(port, "GET", "/feed/")[1]
    token = dict(re.findall(r"data-slug='(\w+)' data-token='([0-9a-f]+)'", page))["demo"]
    body = {"entry_id": FIRST, "ranking_id": RANKING, "reaction": "like"}
    assert _req(port, "POST", "/p/demo/api/feed/react", body, token)[0] == 200
    assert _req(port, "POST", "/p/other/api/feed/react", body, token)[0] == 403
    reacted = [
        ev
        for ev in read_all(project.paths.events_dir, project.catalog)
        if ev.type == "feed.reacted"
    ]
    assert len(reacted) == 1 and reacted[0].actor.kind == "human"
    assert not [
        ev for ev in read_all(two.paths.events_dir, two.catalog) if ev.type == "feed.reacted"
    ]


def test_fetch_now_and_refetch_start_one_run_and_refuse_a_second(
    served: tuple[int, site_server.MainHub, Scripted],
) -> None:
    port, _, script = served
    token = _meta_token(_req(port, "GET", "/feed/")[1])
    assert _req(port, "POST", "/api/feed/run", {}, None)[0] == 403
    script.hold = True
    assert _req(port, "POST", "/api/feed/run", {}, token)[0] == 202
    text = _req(port, "GET", "/api/feed/runner")[1]
    assert json.loads(text)["running"] is True
    assert _req(port, "POST", "/api/feed/refetch", {}, token)[0] == 409
    assert "running" in _req(port, "GET", "/feed/")[1]
    script.release.set()
    for _ in range(100):
        if json.loads(_req(port, "GET", "/api/feed/runner")[1])["running"] is False:
            break
        threading.Event().wait(0.05)
    last = json.loads(_req(port, "GET", "/api/feed/runner")[1])["last"]
    assert last["refetch"] is False and last["exit_code"] == 0
    script.hold = False
    assert _req(port, "POST", "/api/feed/refetch", {}, token)[0] == 202
    for _ in range(100):
        if len(script.calls) == 2:
            break
        threading.Event().wait(0.05)
    assert script.calls == [False, True]


def test_a_project_token_does_not_start_a_run(
    served: tuple[int, site_server.MainHub, Scripted],
) -> None:
    port, _, script = served
    page = _req(port, "GET", "/feed/")[1]
    project_token = re.findall(r"data-slug='demo' data-token='([0-9a-f]+)'", page)[0]
    assert _req(port, "POST", "/api/feed/run", {}, project_token)[0] == 403
    assert script.calls == []


def test_a_failed_run_is_shown_as_the_last_outcome(
    settings: Settings, clock: FixedClock, two: Project
) -> None:
    def boom(refetch: bool) -> FeedRunAll:
        raise RuntimeError("arXiv said no")

    runner = site_server.FeedRunner(boom)
    httpd, _ = _serve(settings, clock, runner)
    try:
        port = httpd.server_address[1]
        token = _meta_token(_req(port, "GET", "/feed/")[1])
        assert _req(port, "POST", "/api/feed/run", {}, token)[0] == 202
        for _ in range(100):
            if runner.last is not None:
                break
            threading.Event().wait(0.05)
        assert "arXiv said no" in _req(port, "GET", "/feed/")[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_without_a_runner_the_page_says_so_and_the_acts_are_refused(
    settings: Settings, clock: FixedClock, two: Project
) -> None:
    httpd, _ = _serve(settings, clock, None)
    try:
        port = httpd.server_address[1]
        page = _req(port, "GET", "/feed/")[1]
        assert "runner is off" in page
        token = _meta_token(page)
        assert _req(port, "POST", "/api/feed/run", {}, token)[0] == 503
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_titles_are_escaped(
    served: tuple[int, site_server.MainHub, Scripted], settings: Settings, project: Project
) -> None:
    from factory.services import site_portal  # noqa: F401

    (settings.root / "registry.json").write_text(
        json.dumps({"projects": {"demo": {"title": "<script>x</script>"}}})
    )
    port, _, _ = served
    page = _req(port, "GET", "/feed/")[1]
    assert "<script>x</script>" not in page and "&lt;script&gt;x&lt;/script&gt;" in page
    assert SECOND not in page


# --- part 4 of the order: the project hub links to the hub page instead of its own product ---


def test_the_project_feed_product_is_a_pointer_to_the_hub_page(
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    from factory.services import site as site_service

    _world(project)
    site_service.build(project, only=["feed"], force=True)
    page = (site_service.site_dir(project) / "feed" / "index.html").read_text(encoding="utf-8")
    assert "href='/feed/'" in page and "target=_top" in page
    assert "<article" not in page and "data-act" not in page and FIRST not in page


def test_the_single_project_server_still_serves_its_feed_folder(project: Project) -> None:
    from factory.services.site import site_dir

    folder = site_dir(project) / "feed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text("<html><head></head><body>pointer</body></html>")
    httpd, _ = site_server.make_server(project, 0, background=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, page = _req(httpd.server_address[1], "GET", "/feed/")
        assert status == 200 and "pointer" in page and "factory-token" in page
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- part 3 of the brief: the project Settings page and its Accept act ---


def _proposal(categories: tuple[str, ...]) -> object:
    from factory.services.feed_categories import CategoryProposal, CategoryShare

    shares = tuple(
        CategoryShare(category=c, works=10 - i, share=(10 - i) / 30)
        for i, c in enumerate(("cs.AI", "cs.CL", "cs.LG"))
    )
    return CategoryProposal(
        categories=categories,
        shares=shares,
        core_works=40,
        with_category=30,
        covered=0.95,
        coverage=0.9,
        minimum=2,
        maximum=4,
    )


def test_settings_shows_the_proposal_and_no_configuration(
    served: tuple[int, site_server.MainHub, Scripted], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import site_settings

    monkeypatch.setattr(
        site_settings, "propose_categories", lambda _p: _proposal(("cs.AI", "cs.CL", "cs.LG"))
    )
    port, _, _ = served
    status, page = _req(port, "GET", "/p/demo/settings/")
    assert status == 200
    assert "not configured" in page
    assert "cs.AI" in page and "cs.CL" in page and "cs.LG" in page
    assert "95%" in page and "of the 30 works" in page and "40 core works" in page
    assert "data-categories='cs.AI,cs.CL,cs.LG'" in page
    assert "name='factory-api' content='/p/demo'" in page and "factory-token" in page
    assert _req(port, "GET", "/p/demo/settings")[0] == 200


def test_settings_with_an_empty_proposal_offers_no_accept(
    served: tuple[int, site_server.MainHub, Scripted], monkeypatch: pytest.MonkeyPatch
) -> None:
    from factory.services import site_settings

    monkeypatch.setattr(site_settings, "propose_categories", lambda _p: _proposal(()))
    port, _, _ = served
    page = _req(port, "GET", "/p/demo/settings/")[1]
    assert "no proposal" in page and "data-act='accept'" not in page


def test_accept_writes_feed_configured_as_the_human_with_the_project_token(
    served: tuple[int, site_server.MainHub, Scripted], project: Project, two: Project
) -> None:
    from factory.services.feed import current_config

    port, _, _ = served
    page = _req(port, "GET", "/p/demo/settings/")[1]
    token = _meta_token(page)
    body = {"categories": ["cs.AI", "cs.CL"]}
    assert _req(port, "POST", "/p/demo/api/feed/configure", body, None)[0] == 403
    other_token = _meta_token(_req(port, "GET", "/p/other/settings/")[1])
    assert _req(port, "POST", "/p/demo/api/feed/configure", body, other_token)[0] == 403
    assert current_config(project) is None
    assert _req(port, "POST", "/p/demo/api/feed/configure", body, token)[0] == 200
    config = current_config(project)
    assert config is not None and config.categories == ("cs.AI", "cs.CL")
    assert current_config(two) is None
    events = [
        ev
        for ev in read_all(project.paths.events_dir, project.catalog)
        if ev.type == "feed.configured"
    ]
    assert len(events) == 1 and events[0].actor.kind == "human"


def test_a_second_accept_keeps_the_other_settings_of_the_configuration(
    served: tuple[int, site_server.MainHub, Scripted], project: Project, clock: FixedClock
) -> None:
    from datetime import timedelta

    from factory.services.feed import configure, current_config

    port, _, _ = served
    configure(project, project.human_actor(), {"categories": ["cs.AI"], "shown_per_cycle": 7})
    clock.advance(timedelta(seconds=5))  # event ids order by time: the later act must sort later
    token = _meta_token(_req(port, "GET", "/p/demo/settings/")[1])
    assert (
        _req(port, "POST", "/p/demo/api/feed/configure", {"categories": ["cs.LG"]}, token)[0] == 200
    )
    config = current_config(project)
    assert config is not None
    assert config.categories == ("cs.LG",) and config.shown_per_cycle == 7
    page = _req(port, "GET", "/p/demo/settings/")[1]
    assert "cs.LG" in page and "shown per cycle" in page and "7" in page


@pytest.mark.parametrize(
    "body", [{}, {"categories": []}, {"categories": "cs.AI"}, {"categories": ["not a category"]}]
)
def test_a_bad_accept_is_refused_and_writes_nothing(
    served: tuple[int, site_server.MainHub, Scripted], project: Project, body: dict[str, object]
) -> None:
    port, _, _ = served
    token = _meta_token(_req(port, "GET", "/p/demo/settings/")[1])
    assert _req(port, "POST", "/p/demo/api/feed/configure", body, token)[0] == 400
    assert not [
        ev
        for ev in read_all(project.paths.events_dir, project.catalog)
        if ev.type == "feed.configured"
    ]


def test_the_act_refuses_a_non_human_actor(project: Project) -> None:
    """The guard is the service's: the page's act cannot be made as the system."""
    from factory.errors import FactoryValidationError
    from factory.services.feed import configure

    with pytest.raises(FactoryValidationError):
        configure(project, project.system_actor(), {"categories": ["cs.AI"]})


def test_the_single_project_server_has_a_settings_page_too(project: Project) -> None:
    httpd, _ = site_server.make_server(project, 0, background=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, page = _req(httpd.server_address[1], "GET", "/settings/")
        assert status == 200 and "name='factory-api' content=''" in page
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- further cards: the ranking beyond the shown items ---


def _demo_section(page: str) -> str:
    return page.split("<section class=pn data-slug='demo'", 1)[1].split("<section", 1)[0]


def test_the_page_counts_shown_of_ranked_and_hides_further_cards_read_only(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    from tests.test_feed_page import world

    port, _, _ = served
    world(project, total=100, shown=29)
    demo = _demo_section(_req(port, "GET", "/feed/")[1])
    assert "Showing <span class=shown-count>30</span> of 100 ranked" in demo
    assert "window 2026-11-10 to 2026-11-11" in demo
    further = re.findall(r"<article class='card further' hidden[^>]*>.*?</article>", demo, re.S)
    assert len(further) == 70  # ranks 30..99; rank 100 is the shown exploration pick
    assert "rank 30, not in the shown set" in further[0]
    assert all(f.count("data-act=") == len(site_hub_feed.ACTIONS) for f in further)
    assert all("reaction: no reaction" in f for f in further)
    assert "data-more='30'" in demo and "Show next 30" in demo
    assert "marked as beyond the shown list" in demo
    assert "Abstract 30 &lt;b&gt;x&lt;/b&gt;" in further[0]
    shown = re.findall(r"<article class=card data-entry-id", demo)
    assert len(shown) == 30


def test_a_further_card_shows_its_reaction_and_added_state(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    from factory.events.reader import read_all as _read
    from factory.model.feed import FeedReaction
    from factory.services.feed import react, send
    from tests.test_feed_page import _eid, world

    port, _, _ = served
    world(project, total=40, shown=5)
    react(project, project.human_actor(), _eid(10), FeedReaction.LIKE)
    send(project, project.human_actor(), _eid(11))
    assert any(
        e.payload.get("beyond_shown") for e in _read(project.paths.events_dir, project.catalog)
    )
    demo = _demo_section(_req(port, "GET", "/feed/")[1])
    cards = {
        m.group(1): m.group(0)
        for m in re.finditer(
            r"<article class='card further' hidden data-entry-id='([^']*)'>.*?</article>",
            demo,
            re.S,
        )
    }
    assert "reaction: like" in cards[_eid(10)] and "badge added" not in cards[_eid(10)]
    assert "badge added" in cards[_eid(11)]
    assert "reaction: no reaction" in cards[_eid(12)]


def test_the_page_says_when_the_cap_cuts(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factory.services import feed_page
    from tests.test_feed_page import world

    port, _, _ = served
    world(project, total=40, shown=5)
    monkeypatch.setattr(feed_page, "DEFAULT_CAP", 10)
    monkeypatch.setattr(feed_page.feed_ranked_page, "__kwdefaults__", {"cap": 10, "records": None})
    demo = _demo_section(_req(port, "GET", "/feed/")[1])
    assert "first 10 ranked entries beyond the shown ones" in demo
    assert "24 more are not listed" in demo


# --- grid layout, clamped abstracts, More ---


def test_the_page_has_the_grid_css_and_the_layout_switch_with_its_storage_key(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    port, _, _ = served
    _world(project)
    page = _req(port, "GET", "/feed/")[1]
    assert "repeat(auto-fill,minmax(380px,1fr))" in page
    assert "-webkit-line-clamp:3" in page and "line-clamp:3" in page
    assert "data-layout=grid" in page and "data-layout=list" in page
    assert "factory-feed-layout" in page
    assert "<details" not in _demo_section(page)


def test_cards_clamp_the_abstract_with_a_more_button_and_authors_only_when_expanded(
    served: tuple[int, site_server.MainHub, Scripted],
    project: Project,
    stub_titles: None,  # noqa: F811
) -> None:
    from tests.test_feed_page import world

    port, _, _ = served
    world(project, total=100, shown=29)
    demo = _demo_section(_req(port, "GET", "/feed/")[1])
    shown = re.findall(r"<article class=card data-entry-id.*?</article>", demo, re.S)
    further = re.findall(r"<article class='card further' hidden[^>]*>.*?</article>", demo, re.S)
    assert shown and further
    for card in shown + further:
        if "class=abs" in card:
            assert "class=tog aria-expanded=false>More</button>" in card
        assert "<details" not in card
        assert card.count("class=meta>") == card.count("<p class=meta>")  # authors only in .au
    assert all(f.startswith("<article class='card further' hidden") for f in further)
    assert demo.count("<div class=grid>") == 1


def test_abstract_block_hides_authors_in_the_expandable_part_and_is_empty_without_abstract() -> (
    None
):
    block = site_hub_feed._abstract_block("Text <b>", "A. One, B. Two")
    assert "<p class=abs>Text &lt;b&gt;</p>" in block
    assert "<p class='meta au'>A. One, B. Two</p>" in block
    assert block.index("class=abs") < block.index("class='meta au'") < block.index("class=tog")
    assert site_hub_feed._abstract_block("", "A. One") == ""
    assert "au'" not in site_hub_feed._abstract_block("Text", "")


def test_more_toggles_the_card_and_aria_expanded_in_a_stub_dom() -> None:
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    harness = """
const classes = new Set(); const attrs = {}; const listeners = {};
const card = {classList: {toggle(c){
  if(classes.has(c)){classes.delete(c);return false;}
  classes.add(c);return true;}}};
const btn = {textContent:'More', closest(){return card;}, setAttribute(k,v){attrs[k]=v;},
  addEventListener(t,f){listeners[t]=f;}, dataset:{}};
const store = {};
global.localStorage = {getItem(k){return store[k]||null;}, setItem(k,v){store[k]=v;}};
global.location = {hash:''}; global.history = {replaceState(){}};
global.document = {
  querySelector(){return null;}, getElementById(){return null;},
  documentElement: {setAttribute(){}},
  querySelectorAll(sel){ return sel==='button.tog' ? [btn] : []; }};
global.fetch = () => Promise.reject(new Error('no'));
eval(process.argv[1]);
listeners.click();
console.log(JSON.stringify([[...classes], attrs['aria-expanded'], btn.textContent]));
listeners.click();
console.log(JSON.stringify([[...classes], attrs['aria-expanded'], btn.textContent]));
"""
    out = subprocess.run(
        [node, "-e", harness, site_hub_feed._SCRIPT], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert json.loads(out[0]) == [["open"], "true", "Less"]
    assert json.loads(out[1]) == [[], "false", "More"]

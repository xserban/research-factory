# ruff: noqa: E501  (the embedded JavaScript has long lines)
"""The main hub's factory feed pages: render tests and, in headless Chromium, click tests.

Same world as `test_site_factory_feed` (two projects, six entries, a fake embedder). The click
tests load a page through a small test-only proxy that injects an error collector and a driver and
forwards everything else (with the hub's own origin, which the write guard compares) to the hub;
the driver writes a JSON result into `#rf-clicks`. Skipped without chromium."""

from __future__ import annotations

import contextlib
import html as htmllib
import http.client
import importlib.util
import json
import re
import shutil
import tempfile
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from factory.clock import FixedClock
from factory.config import Settings
from factory.services import factory_feed as ff
from factory.services import feed as feed_service
from factory.services.context import Project
from tests.helpers import SESSION
from tests.test_factory_feed import FakeEmbedder, world  # noqa: F401 - `world` is a fixture
from tests.test_factory_feed_actions import (
    IDS,
    six,  # noqa: F401 - a fixture
)
from tests.test_site_create import _hub_token, _req
from tests.test_site_factory_feed import _serve


@pytest.fixture
def served(
    six: tuple[Settings, Project, Project],  # noqa: F811
    clock: FixedClock,
) -> Iterator[tuple[int, Settings]]:
    settings, alpha, beta = six
    for project in (alpha, beta):
        feed_service.configure(project, project.human_actor(), {"categories": ("cs.AI", "cs.LG")})
    ff.rank_pool(settings, FakeEmbedder(), session=SESSION, clock=clock)
    httpd, port = _serve(settings, clock, embedder_factory=FakeEmbedder)
    yield port, settings
    httpd.shutdown()
    httpd.server_close()


def _get(port: int, path: str) -> tuple[int, str]:
    return _req(port, "GET", path)


def _react(port: int, entry: str, reaction: str) -> None:
    status, text = _req(
        port,
        "POST",
        "/api/feed/react",
        {"entry_id": entry, "reaction": reaction},
        _hub_token(port, "/feed/"),
    )
    assert status == 200, text


def _count(page: str, key: str) -> int:
    match = re.search(rf"data-count='{key}'>(\d+)<", page)
    assert match is not None, key
    return int(match.group(1))


def _titles(page: str) -> list[str]:
    return re.findall(r"class=fx-title href='https://arxiv.org/abs/([\d.]+)'", page)


# ---------------------------------------------------------------- render


def test_today_lists_every_entry_newest_first_with_the_sidebar_and_token(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    status, page = _get(port, "/feed/")
    assert status == 200
    assert "class=hubbar" in page and "name='factory-token' content='" in page
    assert _titles(page) == [f"2611.0000{n}" for n in (2, 3, 4, 5, 6, 1)]
    assert (
        _count(page, "today") == 6 and _count(page, "liked") == 0 and _count(page, "reading") == 0
    )
    assert "href='/feed/project/alpha/'" in page and "href='/feed/classic/'" in page
    assert "Boxes" not in page and "cs.AI" in page  # category chips from the loaded page
    assert "https://arxiv.org/abs/2611.00001" in page and "Bo Chen" in page
    assert "ranker v" not in page  # no ranker yet: no prediction line


def test_today_is_a_page_of_the_sort_asked_and_bad_values_fall_back(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    newest = _titles(_get(port, "/feed/?sort=newest")[1])
    assert newest[0] == "2611.00002" and newest[-1] == "2611.00001"
    assert _get(port, "/feed/?sort=bogus&page=zzz")[0] == 200
    assert _get(port, "/feed/?page=99")[0] == 200  # clamped to the last page


def test_a_reacted_paper_leaves_today_and_appears_in_liked_with_the_dislike_folded(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    _react(port, IDS[0], "like")
    _react(port, IDS[1], "dislike")
    _react(port, IDS[2], "save")
    today = _get(port, "/feed/")[1]
    assert IDS[0] not in _titles(today) and IDS[1] not in _titles(today)
    assert IDS[2] in _titles(today)  # a save is not a label: it stays in Today, marked saved
    assert (
        _count(today, "today") == 4
        and _count(today, "liked") == 1
        and _count(today, "reading") == 1
    )
    liked = _get(port, "/feed/liked/")[1]
    assert "data-entry-id='" + IDS[0] + "'" in liked and "1 disliked" in liked
    assert "data-act=undo" in liked and IDS[1] in liked
    reading = _get(port, "/feed/reading/")[1]
    assert IDS[2] in reading and "data-act=remove" in reading


def test_undo_and_unsave_supersede_the_earlier_reaction(served: tuple[int, Settings]) -> None:
    port, _ = served
    _react(port, IDS[0], "like")
    _react(port, IDS[0], "unset")
    _react(port, IDS[1], "save")
    _react(port, IDS[1], "unsave")
    assert IDS[0] in _titles(_get(port, "/feed/")[1])
    assert "Nothing liked yet" in _get(port, "/feed/liked/")[1]
    assert "reading list is empty" in _get(port, "/feed/reading/")[1]


def test_train_is_disabled_with_the_reason_below_the_threshold_and_enabled_above(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    page = _get(port, "/feed/")[1]
    assert re.search(r"<button[^>]*id=fx-train disabled", page)
    assert "0 reactions, 5 needed" in page
    for entry, reaction in zip(
        IDS[:5], ["like", "like", "like", "dislike", "dislike"], strict=True
    ):
        _react(port, entry, reaction)
    page = _get(port, "/feed/")[1]
    assert "id=fx-train disabled" not in page and "fx-train-reason" not in page
    assert "3 likes, 2 dislikes" in page


def test_project_page_orders_by_the_project_score_and_names_the_closest_core_work(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    status, page = _get(port, "/feed/project/alpha/?window=all")
    assert status == 200
    ids = _titles(page)
    assert ids[:2] == ["2611.00001", "2611.00002"]  # near A core 1 and A core 2
    assert "similar to A core 1" in page and "id=fx-divider" in page
    assert re.findall(
        r"data-score='(-?[\d.]+)'", page.split("class=fx-list>")[1].split("fx-div")[0]
    )
    assert "<option value='all' selected>" in page
    assert "<option value='7d' selected>" in _get(port, "/feed/project/alpha/?window=bogus")[1]
    assert _get(port, "/feed/project/nobody/")[0] == 404
    assert _get(port, "/feed/project/alpha")[0] == 301


def test_a_card_carries_a_badge_that_links_to_the_project_page(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    page = _get(port, "/feed/")[1]
    assert re.search(r"<a class=chip data-score='0\.9\d+' href='/feed/project/alpha/'", page)
    assert "· in project" in page  # the paper beta already holds


def test_classic_page_stays_at_its_own_path_and_the_old_urls_redirect(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    status, page = _get(port, "/feed/classic/")
    assert status == 200 and "class=tab" in page and "<h1>New papers</h1>" in page
    assert _get(port, "/feed/classic")[0] == 301 and _get(port, "/feed")[0] == 301


def test_assets_are_the_kit_the_fonts_and_the_pages_own_files_only(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    for name in ("kit.css", "feed.css", "feed.js", "fonts/inter-latin.woff2"):
        assert _get(port, f"/feed/assets/{name}")[0] == 200, name
    assert _get(port, "/feed/assets/shell.js")[0] == 404
    assert _get(port, "/feed/assets/../../etc/passwd")[0] == 404


def test_the_page_says_the_feed_is_off_when_the_hub_has_no_factory_feed(
    six: tuple[Settings, Project, Project],  # noqa: F811
    clock: FixedClock,
) -> None:
    settings, _, _ = six
    httpd, port = _serve(settings, clock, env=False)
    try:
        status, page = _get(port, "/feed/")
        assert status == 200 and "feed is off" in page and "/feed/classic/" in page
        assert "name='factory-token' content='" in page
        assert _get(port, "/feed/liked/")[0] == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_send_route_validates_and_needs_the_project_token(served: tuple[int, Settings]) -> None:
    port, _ = served
    page = _get(port, "/feed/")[1]
    tokens = json.loads(htmllib.unescape(re.search(r"data-projects='([^']*)'", page).group(1)))  # type: ignore[union-attr]
    alpha = next(p for p in tokens if p["slug"] == "alpha")
    path = "/p/alpha/api/feed/send"
    assert _req(port, "POST", path, {"entry_id": IDS[0]}, None)[0] == 403
    assert _req(port, "POST", path, {}, alpha["token"])[0] == 400
    # alpha has no project ranking of its own here: the factory ranking holds the entry, so the
    # link goes to alpha's inbox instead
    status, text = _req(port, "POST", path, {"entry_id": IDS[0]}, alpha["token"])
    body = json.loads(text)
    assert status == 200 and body["via"] == "inbox" and body["inbox_item_id"]
    again = json.loads(_req(port, "POST", path, {"entry_id": IDS[0]}, alpha["token"])[1])
    assert again["inbox_item_id"] == body["inbox_item_id"]  # a duplicate writes nothing new
    status, text = _req(port, "POST", path, {"entry_id": "2699.99999"}, alpha["token"])
    assert status == 400 and "unknown" in text  # in no ranking at all: the refusal stands


# ---------------------------------------------------------------- clicks (headless Chromium)

DRIVER = r"""<script>
(function () {
  var SCENARIO = __SCENARIO__;
  var out = {done: false, steps: {}};
  function tick(ms) { return new Promise(function (r) { setTimeout(r, ms || 20); }); }
  async function until(fn, label) {
    for (var i = 0; i < 200; i++) { if (fn()) return true; await tick(25); }
    out.steps['timeout:' + label] = true; return false;
  }
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var num = function (k) { var e = $('[data-count="' + k + '"]'); return e ? parseInt(e.textContent, 10) : null; };
  async function run() {
    if (SCENARIO === 'like') {
      var before = $$('.fx-card').length, id = $('.fx-card').dataset.entryId;
      out.steps.today_before = num('today');
      $('.fx-card [data-act=like]').click();
      await until(function () { return $$('.fx-card').length === before - 1; }, 'card-left');
      out.steps.left = !$('.fx-card[data-entry-id="' + id + '"]');
      out.steps.today_after = num('today'); out.steps.liked_after = num('liked');
      out.steps.toast = ($('.fx-toast') || {}).textContent || '';
    } else if (SCENARIO === 'save') {
      var b = $('.fx-card [data-act=save]');
      b.click();
      await until(function () { return b.getAttribute('aria-pressed') === 'true'; }, 'saved');
      out.steps.pressed = b.getAttribute('aria-pressed'); out.steps.label = b.textContent;
      out.steps.reading = num('reading');
      b.click();
      await until(function () { return b.getAttribute('aria-pressed') === 'false'; }, 'unsaved');
      out.steps.after_toggle = b.textContent; out.steps.reading_after = num('reading');
    } else if (SCENARIO === 'train') {
      var t = $('#fx-train'), panel = $('#fx-settings');
      out.steps.panel_hidden_before = panel.hidden;
      $('#fx-gear').click();
      out.steps.panel_hidden_after = panel.hidden;
      out.steps.disabled = t.disabled;
      out.steps.reason = ($('#fx-train-reason') || {}).textContent || '';
      t.click();  // a disabled button does nothing
      await tick(100);
      out.steps.out = $('#fx-train-out').textContent;
    } else if (SCENARIO === 'train-enabled') {
      $('#fx-gear').click();
      var t2 = $('#fx-train'); out.steps.disabled = t2.disabled;
      t2.click();
      await until(function () { return /Trained/.test($('#fx-train-out').textContent); }, 'trained');
      out.steps.out = $('#fx-train-out').textContent;
    } else if (SCENARIO === 'project') {
      var d = $('#fx-divider'), s = $('#fx-weak');
      out.steps.divider_visible = !d.hidden;
      var next = d.nextElementSibling;
      out.steps.after_divider_score = next ? parseFloat(next.dataset.score) : null;
      var prev = d.previousElementSibling;
      out.steps.before_divider_score = prev ? parseFloat(prev.dataset.score) : null;
      s.value = '0.95'; s.dispatchEvent(new Event('input', {bubbles: true}));
      var hiddenBadges = $$('.fx-badges [data-score]').filter(function (x) { return x.hidden; }).length;
      out.steps.hidden_badges_at_95 = hiddenBadges;
      out.steps.divider_first_at_95 = $('.fx-list').firstElementChild === d || $('.fx-list').firstElementChild.classList.contains('fx-div');
      out.steps.stored = (function () { try { return localStorage.getItem('factory-feed-weak'); } catch (e) { return 'n/a'; } })();
      out.steps.out_text = $('#fx-weak-out').textContent;
      $('#fx-gear').click();
      out.steps.similar = ($('.fx-sim') || {}).textContent || '';
    } else if (SCENARIO === 'liked') {
      var row = $('.fx-row'), n = num('liked'), id2 = row.dataset.entryId;
      out.steps.liked_before = n;
      row.querySelector('[data-act=undo]').click();
      await until(function () { return !$('.fx-row[data-entry-id="' + id2 + '"]'); }, 'row-left');
      out.steps.row_gone = !$('.fx-row[data-entry-id="' + id2 + '"]'); out.steps.liked_after = num('liked');
    } else if (SCENARIO === 'send') {
      var card = $('.fx-card');
      $('[data-act=send]', card).click();
      out.steps.picker = !!$('.fx-pick select', card);
      out.steps.options = $$('.fx-pick select option', card).map(function (o) { return o.value; });
      var go = $('.fx-pick .btn.primary', card); go.click();
      await until(function () { return $('.fx-msg', card); }, 'msg');
      out.steps.msg = ($('.fx-msg', card) || {}).textContent || '';
    } else if (SCENARIO === 'filter') {
      var all = $$('.fx-card').length;
      var q = $('#fx-q'); q.value = 'Paper 3'; q.dispatchEvent(new Event('input', {bubbles: true}));
      out.steps.all = all; out.steps.shown = $$('.fx-card').filter(function (c) { return !c.hidden; }).length;
      var chip = $('.chip[data-cat]'); chip.click();
      out.steps.chip_pressed = chip.getAttribute('aria-pressed');
      var more = $('.fx-more'); out.steps.has_more = !!more;
    }
    out.done = true;
  }
  function finish(err) {
    if (err) window.__rfErrors.push('driver: ' + (err && err.stack ? err.stack : String(err)));
    out.errors = window.__rfErrors;
    var pre = document.createElement('pre'); pre.id = 'rf-clicks';
    pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
  }
  window.addEventListener('load', function () { run().then(function () { finish(); }, finish); });
})();
</script>
"""


class _Proxy(BaseHTTPRequestHandler):
    hub_port = 0
    scenario = ""
    collector = ""

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "origin")}
        headers["Host"] = f"127.0.0.1:{self.hub_port}"
        if self.headers.get("Origin"):
            headers["Origin"] = f"http://127.0.0.1:{self.hub_port}"
        conn = http.client.HTTPConnection("127.0.0.1", self.hub_port, timeout=30)
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        kind = resp.getheader("Content-Type") or ""
        if kind.startswith("text/html") and b"</body>" in data:
            text = data.decode()
            text = text.replace("<head>", "<head>" + self.collector, 1)
            head, _, tail = text.rpartition("</body>")
            data = (
                head + DRIVER.replace("__SCENARIO__", json.dumps(self.scenario)) + "</body>" + tail
            ).encode()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        conn.close()

    do_GET = _forward
    do_POST = _forward

    def log_message(self, *_: object) -> None:
        return


def _drive(hub_port: int, path: str, scenario: str) -> dict[str, Any]:
    from tests.test_hub_ui_clicks import COLLECTOR, PROFILE_ROOT

    handler = type(
        "H", (_Proxy,), {"hub_port": hub_port, "scenario": scenario, "collector": COLLECTOR}
    )
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="rf-feed-", dir=PROFILE_ROOT)
    try:
        dom = _chromium_dom_url(f"http://127.0.0.1:{proxy.server_address[1]}{path}", profile)
    finally:
        proxy.shutdown()
        proxy.server_close()
        shutil.rmtree(profile, ignore_errors=True)
        Path(profile + ".dom").unlink(missing_ok=True)
    marker = '<pre id="rf-clicks">'
    start = dom.find(marker)
    assert start >= 0, "the driver never finished"
    body = dom[start + len(marker) :]
    result: dict[str, Any] = json.loads(htmllib.unescape(body[: body.index("</pre>")]))
    return result


def _chromium_dom_url(url: str, profile: str) -> str:
    """The DOM Chromium dumps for `url`: to a file, in its own process group (as the hub click
    tests do), killed at the end."""
    import os
    import signal
    import subprocess

    out = Path(profile + ".dom")
    with out.open("wb") as sink:
        proc = subprocess.Popen(
            [
                "chromium",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=20000",
                "--dump-dom",
                url,
            ],
            stdout=sink,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            proc.wait(timeout=100)
        except subprocess.TimeoutExpired:
            pass
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    return out.read_text(encoding="utf-8", errors="replace")


browser = pytest.mark.skipif(shutil.which("chromium") is None, reason="chromium is not on PATH")


@browser
@pytest.mark.browser
def test_click_like_removes_the_card_from_today_and_records_it(
    served: tuple[int, Settings], clock: FixedClock
) -> None:
    port, settings = served
    result = _drive(port, "/feed/", "like")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["left"] is True and s["today_after"] == s["today_before"] - 1 and s["liked_after"] == 1
    assert "Liked" in s["toast"]
    assert len(ff.liked(settings, clock=clock)) == 1


@browser
@pytest.mark.browser
def test_click_save_toggles_the_reading_list(
    served: tuple[int, Settings], clock: FixedClock
) -> None:
    port, settings = served
    result = _drive(port, "/feed/", "save")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["pressed"] == "true" and s["label"] == "Saved" and s["reading"] == 1
    assert s["after_toggle"] == "Save" and s["reading_after"] == 0
    assert ff.reading_list(settings, clock=clock) == []  # saved, then unsaved


@browser
@pytest.mark.browser
def test_click_train_is_disabled_with_its_reason_below_the_threshold(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    result = _drive(port, "/feed/", "train")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["panel_hidden_before"] is True and s["panel_hidden_after"] is False
    assert s["disabled"] is True and "5 needed" in s["reason"] and s["out"] == ""


needs_sklearn = pytest.mark.skipif(
    importlib.util.find_spec("sklearn") is None, reason="needs the ranker extra (scikit-learn)"
)


@needs_sklearn
@browser
@pytest.mark.browser
def test_click_train_runs_once_the_threshold_is_met(served: tuple[int, Settings]) -> None:
    port, _ = served
    for entry, reaction in zip(
        IDS[:5], ["like", "like", "like", "dislike", "dislike"], strict=True
    ):
        _react(port, entry, reaction)
    result = _drive(port, "/feed/", "train-enabled")
    assert result["done"] and not result["errors"], result
    assert result["steps"]["disabled"] is False and "ranker v1" in result["steps"]["out"]


@browser
@pytest.mark.browser
def test_click_project_page_weak_line_and_divider(served: tuple[int, Settings]) -> None:
    port, _ = served
    result = _drive(port, "/feed/project/alpha/?window=all", "project")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["divider_visible"] is True
    assert s["before_divider_score"] >= 0.5 > s["after_divider_score"]
    assert s["stored"] == "0.95" and s["out_text"] == "0.95" and s["hidden_badges_at_95"] >= 1
    assert "similar to A core" in s["similar"]


@browser
@pytest.mark.browser
def test_click_undo_on_liked_removes_the_row_and_records_unset(
    served: tuple[int, Settings], clock: FixedClock
) -> None:
    port, settings = served
    _react(port, IDS[0], "like")
    result = _drive(port, "/feed/liked/", "liked")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["row_gone"] is True and s["liked_before"] == 1 and s["liked_after"] == 0
    assert ff.liked(settings, clock=clock) == []


@browser
@pytest.mark.browser
def test_click_send_opens_the_project_picker_and_sends_to_the_inbox(
    served: tuple[int, Settings],
) -> None:
    port, _ = served
    result = _drive(port, "/feed/", "send")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["picker"] is True and s["options"] == ["alpha", "beta"]
    assert "Sent to" in s["msg"]


@browser
@pytest.mark.browser
def test_click_text_filter_and_category_chip(served: tuple[int, Settings]) -> None:
    port, _ = served
    result = _drive(port, "/feed/", "filter")
    assert result["done"] and not result["errors"], result
    s = result["steps"]
    assert s["shown"] == 1 and s["all"] >= 5 and s["chip_pressed"] == "true"


def test_redirects_keep_the_query(served: tuple[int, Settings]) -> None:
    import http.client

    port, _ = served
    for path, location in (
        ("/feed?sort=newest", "/feed/?sort=newest"),
        ("/feed/project/alpha?window=all", "/feed/project/alpha/?window=all"),
    ):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 301 and resp.getheader("Location") == location

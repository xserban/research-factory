"""The main hub's own pages: the portal with its short New papers list, the feed page, the Backlog
and Capabilities pages (factory-wide, so they live here and not in a project hub), each with the
shared bar and its one theme toggle."""

from __future__ import annotations

import pytest

from factory.services import site, site_server
from factory.services.site_theme import THEME_TOGGLE
from tests import test_site_main_hub as _hub
from tests.test_site_main_hub import _get

served = _hub.served  # fixtures of the main hub tests, reused as they are
two = _hub.two


@pytest.mark.parametrize("path", ["/", "/feed/", "/backlog/", "/catalog/"])
def test_every_main_hub_page_has_the_bar_and_exactly_one_toggle(
    served: tuple[int, site_server.MainHub], path: str
) -> None:
    port, _ = served
    status, head, body = _get(port, path)
    assert status == 200 and head["content-type"].startswith("text/html")
    assert "class=hubbar" in body
    assert body.count(THEME_TOGGLE) == 1


@pytest.mark.parametrize(
    ("path", "tab"),
    [("/", "/"), ("/feed/", "/feed/"), ("/backlog/", "/backlog/"), ("/catalog/", "/catalog/")],
)
def test_the_bar_marks_the_page_you_are_on(
    served: tuple[int, site_server.MainHub], path: str, tab: str
) -> None:
    port, _ = served
    body = _get(port, path)[2]
    assert f"href='{tab}' aria-current='page'" in body
    assert body.count("aria-current='page'") == 1


def test_the_portal_has_the_short_feed_list_above_the_project_cards(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    body = _get(port, "/")[2]
    assert "New papers" in body
    assert body.index("New papers") < body.index("href='/p/demo/'")


def test_backlog_and_catalog_paths_without_a_slash_redirect(
    served: tuple[int, site_server.MainHub],
) -> None:
    port, _ = served
    assert _get(port, "/backlog")[0] == 301
    assert _get(port, "/catalog")[0] == 301


def test_the_project_hub_no_longer_lists_the_factory_wide_pages() -> None:
    ids = {p.id for p in site.products()}
    assert "backlog" not in ids and "catalog" not in ids


def test_the_project_sidebar_groups_by_what_the_reader_is_doing() -> None:
    by_group: dict[str, list[str]] = {}
    for p in site.products():
        by_group.setdefault(p.group, []).append(p.id)
    assert list(by_group) == ["Overview", "Sources", "Corpus", "Mining", "Findings"]
    assert by_group["Overview"] == ["dashboard", "prisma", "flow", "documents", "costs"]
    assert by_group["Sources"] == ["search", "feed", "acquisition", "conversion", "queue"]
    assert by_group["Corpus"] == [
        "explorer",
        "bibliography",
        "citations",
        "layers",
        "wiki",
        "updates",
    ]
    assert by_group["Mining"] == ["miners", "agreement", "steps", "lifecycle", "activity", "runs"]
    assert by_group["Findings"] == ["results", "synthesis", "taxonomy"]
    # every product is in exactly one group
    assert sorted(i for ids in by_group.values() for i in ids) == sorted(
        p.id for p in site.products()
    )

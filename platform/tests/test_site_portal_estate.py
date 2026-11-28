"""Tests for the estate portal (P01): JSON data blob, escaping, forms, served assets, and tokens."""

from __future__ import annotations

import json
import re
from pathlib import Path

from factory.services import site_factory_feed, site_portal

_HUB_UI = Path(__file__).parents[1] / "src/factory/hub_ui"
_LITERAL_COLOR = re.compile(r"(#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\bhsla?\s*\()")
_EXTERNAL_URL = re.compile(r"https?://")


def _extract_pt_data(page: str) -> dict[str, object]:
    m = re.search(
        r"<script\s+type=['\"]?application/json['\"]?\s+id=['\"]?pt-data['\"]?>(.*?)</script>",
        page,
        re.S,
    )
    assert m is not None, "missing <script type='application/json' id='pt-data'>"
    return json.loads(m.group(1))


def test_pt_data_blob_is_valid_json_with_expected_project_fields() -> None:
    row = site_portal.PortalRow(
        slug="alpha",
        title="Alpha Review",
        events=420,
        stale=3,
        built=7,
        hub_ready=True,
        building=False,
        activity=(0, 5, 12),
        activity_end="2026-11-28",
        funnel=(1000, 400, 50),
    )
    page = site_portal.render_portal([row])
    data = _extract_pt_data(page)
    projects = data["projects"]
    assert isinstance(projects, list) and len(projects) == 1
    p = projects[0]
    assert p == {
        "slug": "alpha",
        "title": "Alpha Review",
        "events": 420,
        "stale": 3,
        "built": 7,
        "hub_ready": True,
        "building": False,
        "activity": [0, 5, 12],
        "activity_end": "2026-11-28",
        "funnel": {"found": 1000, "screened": 400, "included": 50},
        "hub_url": "/p/alpha/ui/",
        "classic_url": "/p/alpha/",
    }


def test_script_close_tag_in_title_cannot_break_out_of_pt_data() -> None:
    evil = "Bad </script><script>alert(1)</script> Title"
    row = site_portal.PortalRow("evil", evil, 1, 0, 1, True)
    page = site_portal.render_portal([row])
    m = re.search(
        r"<script\s+type=['\"]?application/json['\"]?\s+id=['\"]?pt-data['\"]?>(.*?)</script>",
        page,
        re.S,
    )
    assert m is not None
    raw_blob = m.group(1)
    assert "</script>" not in raw_blob.lower()
    parsed = json.loads(raw_blob)
    assert parsed["projects"][0]["title"] == evil


def test_forms_keep_exact_names_ids_and_endpoints() -> None:
    row = site_portal.PortalRow("demo", "Demo", 10, 0, 2, True)
    page = site_portal.render_portal([row], create_token="tok-123")
    assert "meta name='factory-token' content='tok-123'" in page
    assert "id=create-form" in page
    assert "name=slug" in page and "name=title" in page and "name=profile" in page
    assert "/api/projects/create" in page
    assert "id=inbox-form" in page
    assert "name=project" in page and "name=value" in page and "name=note" in page
    assert "/api/inbox/add" in page


def test_estate_assets_are_served_and_linked_in_portal() -> None:
    css_asset = site_factory_feed.asset("estate.css")
    js_asset = site_factory_feed.asset("estate.js")
    assert css_asset is not None and "text/css" in css_asset[1]
    assert js_asset is not None and "javascript" in js_asset[1]
    page = site_portal.render_portal([])
    assert "/feed/assets/estate.css?v=" in page
    assert "/feed/assets/estate.js?v=" in page


def test_estate_assets_have_no_literal_colors_or_external_urls() -> None:
    for name in ("estate.css", "estate.js"):
        text = (_HUB_UI / name).read_text(encoding="utf-8")
        assert not _LITERAL_COLOR.search(text), f"literal colour found in {name}"
        assert not _EXTERNAL_URL.search(text), f"external URL found in {name}"


def test_funnel_none_stays_null_in_payload_and_blob() -> None:
    row = site_portal.PortalRow(
        slug="beta",
        title="Beta",
        events=0,
        stale=0,
        built=0,
        hub_ready=False,
        building=False,
        activity=(),
        activity_end=None,
        funnel=None,
    )
    assert site_portal.portal_payload([row])["projects"][0]["funnel"] is None  # type: ignore[index]
    data = _extract_pt_data(site_portal.render_portal([row]))
    assert data["projects"][0]["funnel"] is None  # type: ignore[index]


def test_estate_js_keeps_unread_counts_distinct_and_guards_interactions() -> None:
    js = site_factory_feed.asset("estate.js")
    assert js is not None
    text = js[0].decode()
    assert "countsRead" in text and "counts not read" in text
    assert "ev.ctrlKey || ev.metaKey" in text
    assert "&#39;" in text
    assert "ev.key !== 'Escape'" in text
    row = site_portal.PortalRow(
        slug="g", title="G", events=1, stale=0, built=0, hub_ready=False,
        building=False, activity=(), activity_end=None, funnel=None,
    )
    assert "Ctrl + scroll to zoom" in site_portal.render_portal([row])

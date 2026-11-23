"""The backlog page is a hub v2 kit page: kit stylesheets, one bar, kit tokens only."""

from __future__ import annotations

import re

import pytest

from factory.services import site_backlog


def _check(doc: str) -> None:
    assert "kit.css" in doc and "main-hub.css" in doc
    assert doc.count("class=hubbar") == 1
    # the page's own sheet is the first inline <style>; the shared bar adds its own after it
    style = re.findall(r"<style>(.*?)</style>", doc, re.S)[0]
    assert ".bl-" in style and not re.search(r"#[0-9a-fA-F]{3,8}\b", style)


def test_backlog_page_is_a_kit_page() -> None:
    _check(site_backlog.render_backlog())


def test_backlog_missing_says_what_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_backlog, "backlog_path", lambda: None)
    doc = site_backlog.render_backlog()
    _check(doc)
    assert "FACTORY_BACKLOG" in doc

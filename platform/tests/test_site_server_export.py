# ruff: noqa: F811, F401
"""The hub's export route (IDEA-87): `POST /api/export/works` answers a zip, as the local human,
behind the same token, origin and permission gates as the other acts, and writes no event."""

from __future__ import annotations

import http.client
import io
import json
import re
import threading
import zipfile
from collections.abc import Iterator
from typing import Any

import pytest

from factory.errors import FactoryError
from factory.services import site_server, withholding
from factory.services.context import Project
from factory.services.site import site_dir
from tests.test_export_works import _event_files, two


@pytest.fixture
def served(project: Project, two: tuple[str, str]) -> Iterator[tuple[int, str]]:
    page = site_dir(project) / "explorer"
    page.mkdir(parents=True, exist_ok=True)
    (page / "index.html").write_text("<html><head></head><body>x</body></html>", encoding="utf-8")
    httpd, _ = site_server.make_server(project, 0, background=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/explorer/")
    body = conn.getresponse().read().decode()
    conn.close()
    match = re.search(r"name='factory-token' content='([^']+)'", body)
    assert match is not None
    yield port, match.group(1)
    httpd.shutdown()
    httpd.server_close()


def _post(
    port: int, body: dict[str, Any], token: str | None, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], bytes]:
    sent = {"Content-Type": "application/json", **(headers or {})}
    if token is not None:
        sent["X-Factory-Token"] = token
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("POST", "/api/export/works", body=json.dumps(body), headers=sent)
    response = conn.getresponse()
    data = response.read()
    heads = {k.lower(): v for k, v in response.getheaders()}
    conn.close()
    return response.status, heads, data


def test_a_selection_is_answered_as_a_zip_and_writes_no_event(
    project: Project,
    served: tuple[int, str],
    two: tuple[str, str],
) -> None:
    port, token = served
    before = _event_files(project)
    status, heads, data = _post(port, {"work_ids": list(two)}, token)
    assert status == 200
    assert heads["content-type"] == "application/zip"
    assert "attachment" in heads["content-disposition"] and ".zip" in heads["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert len(manifest["works"]) == 1 and len(manifest["skipped"]) == 1
        assert manifest["selection"] == "selected in the explorer"
    assert _event_files(project) == before


def test_pdfs_flag_reaches_the_service(
    served: tuple[int, str],
    two: tuple[str, str],
) -> None:
    port, token = served
    _, _, data = _post(port, {"work_ids": [two[0]], "pdfs": True}, token)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert json.loads(z.read("manifest.json"))["pdfs"] == "included where stored"


def test_missing_token_and_foreign_origin_are_refused(
    served: tuple[int, str],
    two: tuple[str, str],
) -> None:
    port, token = served
    assert _post(port, {"work_ids": [two[0]]}, None)[0] == 403
    assert _post(port, {"work_ids": [two[0]]}, token, {"Origin": "http://evil.example"})[0] == 403


def test_a_refused_command_is_403_and_exports_nothing(
    served: tuple[int, str],
    two: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, token = served
    seen: list[str] = []

    def refuse(project: Project, principal: Any, tool: str) -> None:
        seen.append(tool)
        raise FactoryError("not allowed")

    monkeypatch.setattr(site_server, "authorize_command", refuse)
    status, _, data = _post(port, {"work_ids": [two[0]]}, token)
    assert status == 403 and seen == ["cli:export works"]
    assert json.loads(data)["ok"] is False


def test_bad_bodies_and_the_cap_are_structured_400s(
    served: tuple[int, str],
    two: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, token = served
    assert _post(port, {"work_ids": []}, token)[0] == 400
    assert _post(port, {"work_ids": "rf:a"}, token)[0] == 400
    monkeypatch.setattr("factory.services.export_works.MAX_WORKS", 1)
    status, _, data = _post(port, {"work_ids": list(two)}, token)
    assert status == 400 and json.loads(data)["issues"][0]["field"] == "selection"


def test_a_held_out_work_is_withheld_over_the_hub_too(
    served: tuple[int, str],
    two: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port, token = served
    monkeypatch.setattr(withholding, "held_out_tokens", lambda p, include_work_ids=True: {two[0]})
    _, _, data = _post(port, {"work_ids": [two[0]]}, token)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["withheld"] == 1 and two[0] not in json.dumps(manifest)


def test_a_body_larger_than_the_usual_limit_is_taken_for_this_route(
    served: tuple[int, str],
    two: tuple[str, str],
) -> None:
    port, token = served
    ids = [two[0]] + [f"rf:filler-{i:04d}-{'x' * 60}" for i in range(250)]
    status, _, data = _post(port, {"work_ids": ids}, token)
    assert status == 400 and json.loads(data)["issues"][0]["field"] == "selection"

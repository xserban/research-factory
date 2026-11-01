from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from factory.config import Settings
from factory.sources.http import HOST_INTERVALS, PoliteClient, default_http, user_agent

ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
OTHER = "https://example.org/data"


class FakeTime:
    """Fake clock: sleep() records the duration and advances the clock that monotonic() reads."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    time: FakeTime,
    **kwargs: Any,
) -> PoliteClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return PoliteClient(http, sleep=time.sleep, monotonic=time.monotonic, **kwargs)


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="ok")


def test_requests_to_one_host_are_spaced_by_its_interval() -> None:
    time = FakeTime()
    client = make_client(ok, time)
    for _ in range(3):
        assert client.get(ARXIV, params={"q": "x"}).status_code == 200
    assert time.sleeps == pytest.approx([3.0, 3.0])


def test_hosts_are_throttled_independently() -> None:
    time = FakeTime()
    client = make_client(ok, time)
    client.get(ARXIV, params={})
    client.get(OPENALEX, params={})
    assert time.sleeps == []


def test_default_intervals_match_the_brief() -> None:
    assert HOST_INTERVALS == {"export.arxiv.org": 3.0, "api.openalex.org": 0.1}


def test_retry_after_header_is_honoured_and_capped() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    time = FakeTime()
    client = make_client(lambda _: next(responses), time)
    assert client.get(OTHER, params={}).status_code == 200
    assert time.sleeps == [7.0]

    responses = iter([httpx.Response(429, headers={"Retry-After": "9999"}), httpx.Response(200)])
    time = FakeTime()
    client = make_client(lambda _: next(responses), time)
    client.get(OTHER, params={})
    assert time.sleeps == [300.0]


def test_retry_after_http_date_falls_back_to_backoff() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            httpx.Response(200),
        ]
    )
    time = FakeTime()
    client = make_client(lambda _: next(responses), time)
    client.get(OTHER, params={})
    assert time.sleeps == [2.0]


def test_server_errors_are_retried_then_raised() -> None:
    calls: list[httpx.Request] = []

    def always_503(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    time = FakeTime()
    client = make_client(always_503, time, retries=4)
    with pytest.raises(httpx.HTTPStatusError):
        client.get(OTHER, params={})
    assert len(calls) == 5
    assert time.sleeps == [2.0, 4.0, 8.0, 16.0]


def test_transport_errors_are_retried() -> None:
    attempts = iter([httpx.ConnectError("boom"), None])

    def flaky(request: httpx.Request) -> httpx.Response:
        error = next(attempts)
        if error is not None:
            raise error
        return httpx.Response(200, text="ok")

    time = FakeTime()
    client = make_client(flaky, time)
    assert client.get(OTHER, params={}).status_code == 200
    assert time.sleeps == [2.0]


def test_transport_error_on_final_attempt_is_reraised() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    time = FakeTime()
    client = make_client(down, time, retries=2)
    with pytest.raises(httpx.ConnectError):
        client.get(OTHER, params={})
    assert time.sleeps == [2.0, 4.0]


def test_client_errors_are_not_retried() -> None:
    calls: list[httpx.Request] = []

    def not_found(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    time = FakeTime()
    client = make_client(not_found, time)
    with pytest.raises(httpx.HTTPStatusError):
        client.get(OTHER, params={})
    assert len(calls) == 1
    assert time.sleeps == []


def test_user_agent_carries_mailto_only_when_configured() -> None:
    assert user_agent(None) == "research-factory/0.2"
    assert user_agent("someone@example.org") == "research-factory/0.2 (mailto:someone@example.org)"


def test_default_http_sets_timeout_redirects_and_user_agent(tmp_path: Path) -> None:
    settings = Settings(root=tmp_path, user="obd", mailto="someone@example.org")
    client = default_http(settings)
    http = client._http
    assert http.timeout.read == 60.0
    assert http.follow_redirects is True
    assert http.headers["User-Agent"] == "research-factory/0.2 (mailto:someone@example.org)"

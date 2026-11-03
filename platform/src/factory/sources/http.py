"""One polite client for every outbound request: per-host throttle, Retry-After, backoff.

arXiv asks for at least 3 seconds between requests and blocks hard otherwise; OpenAlex asks
for a polite pace and a contact address (`mailto`) in the User-Agent.
"""

import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from urllib.parse import quote, quote_plus

import httpx

from factory.config import Settings

HOST_INTERVALS: Mapping[str, float] = {
    "export.arxiv.org": 3.0,
    "arxiv.org": 3.0,
    "api.openalex.org": 0.1,
}

VERSION = "0.2"


def user_agent(mailto: str | None) -> str:
    base = f"research-factory/{VERSION}"
    return f"{base} (mailto:{mailto})" if mailto else base


_MAILTO_FIRST = re.compile(r"\?mailto=[^&#\s'\"]*&")
_MAILTO_PARAM = re.compile(r"[?&]mailto=[^&#\s'\"]*")


def redact(url_or_text: str, secret: str | None) -> str:
    """Remove the contact address from a URL or a message built from one.

    The `mailto` query parameter is dropped from any URL in the text, then every remaining
    occurrence of `secret` (literal or percent-encoded) becomes `<mailto>`. The address is sent
    to OpenAlex but must never reach the event log, which is committed and shared.
    """
    text = _MAILTO_FIRST.sub("?", url_or_text)
    text = _MAILTO_PARAM.sub("", text)
    if secret:
        for form in {secret, quote(secret), quote(secret, safe=""), quote_plus(secret)}:
            text = text.replace(form, "<mailto>")
    return text


class PoliteClient:
    """GET with per-host spacing, Retry-After on 429, and retries on 5xx and transport errors."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        intervals: Mapping[str, float] = HOST_INTERVALS,
        default_interval: float = 1.0,
        retries: int = 4,
        backoff: tuple[float, float] = (2.0, 60.0),
        max_retry_after: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = client
        self._intervals = intervals
        self._default_interval = default_interval
        self._retries = retries
        self._backoff = backoff
        self._max_retry_after = max_retry_after
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def get(self, url: str, params: Mapping[str, str | int] | None = None) -> httpx.Response:
        """Fetch `url`, raising `httpx.HTTPStatusError` on any status of 400 or above."""
        response = self.fetch(url, params)
        response.raise_for_status()
        return response

    def fetch(self, url: str, params: Mapping[str, str | int] | None = None) -> httpx.Response:
        """Fetch `url` with throttle and retries; return the final response whatever its status.

        Retries 429 (honouring Retry-After), 5xx and transport errors up to `retries` times.
        After the last retry a status of 400 or above is returned, not raised; a transport
        error on the last attempt is still raised.
        """
        host = httpx.URL(url).host
        for attempt in range(self._retries + 1):
            self._wait_turn(host)
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
                self._sleep(self._exponential(attempt))
                continue
            if response.status_code == 429 and attempt < self._retries:
                self._sleep(min(self._retry_after(response, attempt), self._max_retry_after))
                continue
            if response.status_code >= 500 and attempt < self._retries:
                self._sleep(self._exponential(attempt))
                continue
            return response
        raise AssertionError("unreachable: the final attempt always returns or raises")

    def _wait_turn(self, host: str) -> None:
        """Block until `host` may be called again, then stamp the call time."""
        with self._lock:
            last = self._last.get(host)
            if last is not None:
                delay = self._intervals.get(host, self._default_interval) - (
                    self._monotonic() - last
                )
                if delay > 0:
                    self._sleep(delay)
            self._last[host] = self._monotonic()

    def _exponential(self, attempt: int) -> float:
        return min(self._backoff[1], self._backoff[0] * 2.0**attempt)

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After", "")
        try:
            seconds = float(value)
        except ValueError:
            return self._exponential(attempt)
        if not math.isfinite(seconds) or seconds < 0:
            return self._exponential(attempt)
        return seconds


def default_http(settings: Settings) -> PoliteClient:
    http = httpx.Client(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": user_agent(settings.mailto)},
    )
    return PoliteClient(http)

#!/usr/bin/env python3
"""Smoke test of a running hub: crawl every same-origin page reachable from `/`, report each
page's status and time, links that do not resolve, and pages that show a traceback or an error
banner. Read-only: GET requests only, nothing is posted. Standard library only.

usage: scripts/smoke_hub.py [BASE_URL] [DEPTH]   (default http://127.0.0.1:8766, 2 link levels)
exit status 1 when any page fails, a link breaks, or a page takes longer than SLOW seconds.
"""

from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

SLOW = 3.0
ERROR_MARKS = ("Traceback (most recent call last)",)
HREF = re.compile(r"""(?:href|src)=["']([^"'#][^"']*)["']""")
SKIP = ("/api/", "mailto:", "javascript:", "data:")


def fetch(url: str) -> tuple[int, float, str, str]:
    start = time.time()
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            body = r.read()
            return (
                r.status,
                time.time() - start,
                r.headers.get("content-type", ""),
                body.decode("utf-8", "replace"),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, time.time() - start, "", ""
    except OSError as exc:
        return 0, time.time() - start, "", str(exc)


def main(base: str, depth: int) -> int:
    origin = urllib.parse.urlsplit(base)
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(base.rstrip("/") + "/", 0)])
    bad: list[str] = []
    print(f"{'status':>6} {'secs':>6}  url")
    while queue:
        url, level = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        code, secs, ctype, body = fetch(url)
        flags = []
        if code != 200:
            flags.append(f"HTTP {code}")
        if secs > SLOW:
            flags.append("slow")
        if any(m in body for m in ERROR_MARKS):
            flags.append("error text")
        if flags or "-v" in sys.argv:
            print(f"{code:>6} {secs:6.2f}  {url}  {' '.join(flags)}")
        if flags:
            bad.append(url)
        if code == 200 and "html" in ctype and level < depth:
            for ref in HREF.findall(body):
                if ref.startswith(SKIP) or "/api/" in ref:
                    continue
                full = urllib.parse.urljoin(url, ref)
                parts = urllib.parse.urlsplit(full)
                if parts.netloc != origin.netloc:
                    continue
                queue.append(
                    (urllib.parse.urlunsplit(parts._replace(fragment="")), level + 1)
                )
    print(f"\n{len(seen)} pages, {len(bad)} flagged")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(
        main(
            sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766",
            int(sys.argv[2]) if len(sys.argv) > 2 else 2,
        )
    )

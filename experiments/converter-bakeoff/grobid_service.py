"""Start, stop or probe the local GROBID service (`./gradlew run` with the local JDK, port 8070).

Usage: `uv run python grobid_service.py start|stop|status`. Everything stays under `tools/`; the
service log is `tools/grobid/service.log` and the pid file `tools/grobid/service.pid`.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time

import httpx

from adapters._common import GROBID_DIR, JAVA_HOME

PID = GROBID_DIR.parent / "service.pid"
LOG = GROBID_DIR.parent / "service.log"
ALIVE = "http://localhost:8070/api/isalive"


def alive() -> bool:
    try:
        return httpx.get(ALIVE, timeout=3).text.strip() == "true"
    except httpx.HTTPError:
        return False


def start(timeout: int = 600) -> int:
    if alive():
        print("already running")
        return 0
    env = {
        **os.environ,
        "JAVA_HOME": str(JAVA_HOME),
        "PATH": f"{JAVA_HOME}/bin:{os.environ['PATH']}",
    }
    with LOG.open("ab") as log:
        proc = subprocess.Popen(
            ["./gradlew", "run"],
            cwd=GROBID_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID.write_text(str(proc.pid))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if alive():
            print("up")
            return 0
        if proc.poll() is not None:
            print(f"gradle exited {proc.returncode}; see {LOG}", file=sys.stderr)
            return 1
        time.sleep(3)
    print("timeout waiting for GROBID", file=sys.stderr)
    return 1


def stop() -> int:
    if PID.exists():
        with contextlib.suppress(ProcessLookupError):
            os.killpg(int(PID.read_text()), signal.SIGTERM)
        PID.unlink()
    # gradle's forked JVM may outlive the process group on some setups
    subprocess.run(["pkill", "-f", "org.grobid.service.main.GrobidServiceApplication"], check=False)
    print("stopped")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "start":
        sys.exit(start())
    if action == "stop":
        sys.exit(stop())
    print("up" if alive() else "down")

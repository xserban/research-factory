"""The autouse fixture in conftest removes the shell FACTORY_* variables."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_factory_variables_of_the_shell_are_absent() -> None:
    """Run in a child that inherits a polluted environment: pytest itself starts with
    FACTORY_ROOT and FACTORY_PLUGIN_DIR set, and the test inside must not see them."""
    env = dict(
        os.environ,
        FACTORY_ROOT="/nonexistent/pilot",
        FACTORY_PLUGIN_DIR="/nonexistent/plugin",
        FACTORY_USER="someone",
        FACTORY_TEST_ISOLATION_CHILD="1",
    )
    code = (
        "import pytest, sys;"
        "sys.exit(pytest.main(['-q','-p','no:warnings','-p','no:cacheprovider',"
        "'tests/test_env_isolation.py::test_probe_inside']))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(
    not os.environ.get("FACTORY_TEST_ISOLATION_CHILD"), reason="run only from the child"
)
def test_probe_inside() -> None:  # pragma: no cover - executed in the child process
    assert "FACTORY_ROOT" not in os.environ
    assert "FACTORY_PLUGIN_DIR" not in os.environ
    assert "FACTORY_USER" not in os.environ
    assert os.environ["FACTORY_HUB_PREWARM"] == "0"


def test_a_test_can_still_set_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "FACTORY_ROOT" not in os.environ
    monkeypatch.setenv("FACTORY_PLUGIN_DIR", "/somewhere")
    assert os.environ["FACTORY_PLUGIN_DIR"] == "/somewhere"

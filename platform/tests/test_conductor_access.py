"""The conductor commands declare a permission, so a lab server root does not refuse them as
undeclared (`command_permission`): `status` reads, `start` and `advance` start runs (`work:run`,
as `queue advance` does) and an observer does not hold that."""

from __future__ import annotations

import pytest

from factory.cli.conductor import conductor_app
from factory.errors import FactoryValidationError
from factory.model.members import ProjectRole
from factory.services.access import ROLE_PERMISSIONS, Permission
from factory.services.cli_access import command_permission


def _commands() -> list[str]:
    return [
        c.name or (c.callback.__name__.removesuffix("_cmd") if c.callback else "")
        for c in conductor_app.registered_commands
    ]


def test_every_conductor_command_declares_a_permission() -> None:
    assert sorted(_commands()) == ["advance", "start", "status"]
    for name in _commands():
        command_permission(f"cli:conductor {name}")  # raises when undeclared


def test_status_reads_and_start_and_advance_run_work() -> None:
    assert command_permission("cli:conductor status") is Permission.PROJECT_READ
    assert command_permission("cli:conductor start") is Permission.WORK_RUN
    assert command_permission("cli:conductor advance") is Permission.WORK_RUN


def test_an_observer_may_read_the_status_but_not_start_or_advance() -> None:
    held = ROLE_PERMISSIONS[ProjectRole.OBSERVER]
    assert command_permission("cli:conductor status") in held
    assert command_permission("cli:conductor start") not in held
    assert command_permission("cli:conductor advance") not in held
    assert command_permission("cli:conductor advance") in ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]


def test_an_undeclared_command_is_still_refused() -> None:
    with pytest.raises(FactoryValidationError):
        command_permission("cli:conductor nonsense")

"""Declarations that bind the services to the stage-module contract (slice M).

This package is import-light on purpose: `stages` imports it for the task kinds, and the
declarations of the modules import the services' constants. `default_modules` is imported on
first call so that importing the package costs nothing.
"""

from typing import TYPE_CHECKING

from factory.services.modules.task_kinds import default_task_kinds

if TYPE_CHECKING:
    from factory.modules.registry import ModuleRegistry

__all__ = ["default_modules", "default_task_kinds"]


def default_modules() -> "ModuleRegistry":
    """The registry of the built modules (see `services/modules/default.py`)."""
    from factory.services.modules.default import default_modules as build

    return build()

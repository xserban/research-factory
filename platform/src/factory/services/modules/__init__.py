"""Declarations that bind the services to the stage-module contract (slice M).

This package is import-light on purpose: `stages` imports it for the task kinds, and the
declarations of the modules import the services. `default_modules` is therefore imported on
first call.
"""

from factory.services.modules.task_kinds import default_task_kinds

__all__ = ["default_task_kinds"]

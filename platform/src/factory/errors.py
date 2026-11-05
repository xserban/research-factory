from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    """One located problem with an input: `field` names the offending part."""

    field: str
    reason: str


class FactoryError(Exception):
    """Base class for all platform errors."""


class FactoryValidationError(FactoryError):
    """Input failed validation; nothing was written."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(f"{i.field}: {i.reason}" for i in self.issues))


class OrderingError(FactoryError):
    """An event of a hosted project was minted outside `Project.writing()`: its ID does not sort
    after the log. A programming error, never a user's; nothing was written."""


class ProjectNotFoundError(FactoryError):
    """No project with the requested slug exists."""

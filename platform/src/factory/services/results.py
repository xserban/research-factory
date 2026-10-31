from typing import Generic, TypeVar

from pydantic import BaseModel

from factory.errors import ValidationIssue
from factory.model.base import StrictModel

T = TypeVar("T")


class ItemError(StrictModel):
    """Why one item of a batch was rejected: its position in the input and the issues."""

    index: int
    issues: list[ValidationIssue]


class BatchResult(BaseModel, Generic[T]):
    """Valid items were written (in input order); invalid ones were reported, not written."""

    written: list[T]
    rejected: list[ItemError]

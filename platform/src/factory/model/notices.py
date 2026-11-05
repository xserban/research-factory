"""Notices of retraction, correction and the like about a known work (slice 4b, living-C).

A notice is observed from source metadata, never typed by an agent. Its effects are computed at
read time from `notice.observed` and `notice.assessed` events by a single pure function; nothing
here is stored as a derived status.
"""

from __future__ import annotations

from enum import StrEnum


class NoticeKind(StrEnum):
    RETRACTION = "retraction"
    WITHDRAWAL = "withdrawal"
    CORRECTION = "correction"
    EXPRESSION_OF_CONCERN = "expression-of-concern"
    REINSTATEMENT = "reinstatement"

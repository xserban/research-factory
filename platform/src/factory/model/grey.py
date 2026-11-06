"""Grey literature: the declared sources and the reported events (plan SG, PD-7 provisional).

Grey evidence is labelled and never pooled silently. A grey source is declared in the protocol
section `grey_sources`; the section is left out of every hash while absent.

Invariants: a declared plan has no repeated `(method, target)` and is never agent web search
alone; a reported search carries its stopping rule; a reported search enrols nothing (its URLs
become inbox items).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from factory.model.base import StrictModel
from factory.model.identity import ULID_RE

GREY_SEARCH_ID_RE = rf"^grs_{ULID_RE}$"
GREY_CONTACT_ID_RE = rf"^grc_{ULID_RE}$"
MAX_URLS = 200

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class GreyMethod(StrEnum):
    STRUCTURED = "structured"  # OpenAlex types such as `report` and `dissertation`
    WEBSITE = "website"  # a declared URL list, captured
    AGENT_WEB_SEARCH = "agent-web-search"  # run in the agent, reported through a tool
    EXPERT_CONTACT = "expert-contact"  # a contact log


class GreySource(StrictModel):
    """One declared grey source.

    `target` names what is searched: for `structured`, comma-separated OpenAlex types; for
    `website` a site; for `agent-web-search` an engine; for `expert-contact` a person or role
    label. `stopping_rule` states when searching ends (the explicit R-21 exception).
    `included` is whether its works are pooled with the rest; reports show both counts.
    """

    method: GreyMethod
    target: Text
    stopping_rule: Text
    included: bool = True


def grey_source_issues(sources: tuple[GreySource, ...]) -> list[tuple[str, str]]:
    """(field, reason) pairs: empty, a repeated (method, target), or agent web search alone."""
    issues: list[tuple[str, str]] = []
    if not sources:
        return [("grey_sources", "needs at least one entry, or leave the section out")]
    keys = [(s.method, s.target) for s in sources]
    if len(set(keys)) != len(keys):
        issues.append(("grey_sources", "must not repeat a (method, target)"))
    if all(s.method is GreyMethod.AGENT_WEB_SEARCH for s in sources):
        issues.append(("grey_sources", "agent web search cannot be the only grey method"))
    return issues


def structured_types(sources: tuple[GreySource, ...] | None) -> frozenset[str]:
    """The OpenAlex work types the `structured` entries authorise."""
    found: set[str] = set()
    for source in sources or ():
        if source.method is GreyMethod.STRUCTURED:
            found.update(t.strip() for t in source.target.split(",") if t.strip())
    return frozenset(found)


class GreySearchReported(StrictModel):
    """Payload of `grey.search_reported`: a web search run in the agent, reported afterwards.

    Neither the engine nor its ranking is verifiable here; the event records what the agent
    said it ran. `urls` are offered to the inbox; no work is enrolled by this event."""

    report_id: str = Field(pattern=GREY_SEARCH_ID_RE)
    target: Text
    engine: Text
    query: Text
    timestamp: AwareDatetime
    urls: tuple[Text, ...] = Field(max_length=MAX_URLS)
    stopping_rule: Text

    @field_validator("urls")
    @classmethod
    def _unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("urls must not repeat")
        return value


class GreyContactLogged(StrictModel):
    """Payload of `grey.contact_logged`: an expert contact. `target` is a label or role, not a
    personal address; `summary` states what was asked and what came back."""

    contact_id: str = Field(pattern=GREY_CONTACT_ID_RE)
    target: Text
    contacted_on: AwareDatetime
    summary: Text = Field(max_length=2000)
    urls: tuple[Text, ...] = Field(default=(), max_length=MAX_URLS)

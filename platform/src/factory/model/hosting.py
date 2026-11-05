from pydantic import Field

from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE


class ProjectHosted(StrictModel):
    """From this event on, `host_id` is the only writer of the project (slice 5 ruling 2).

    `previous_host` is the host this event replaces, read from the fold; a project moves to another
    host by a new event, never by an edit (ruling 19)."""

    host_id: str = Field(pattern=ACTOR_ID_RE)
    previous_host: str | None = Field(default=None, pattern=ACTOR_ID_RE)

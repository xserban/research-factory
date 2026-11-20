"""Types of the tutorial data (`factory.learn`): static content, no behaviour.

Invariants: every model is frozen; a `Ref` names one skill, MCP tool, CLI command path or hub page,
and `tests/test_learn_content.py` checks each against the code, so the tutorial cannot name a
thing that does not exist. The tutorial judges nothing: it holds text, and progress is computed
elsewhere (`services/learn_progress.py`) from the project's own facts.
"""

from dataclasses import dataclass
from enum import StrEnum


class Actor(StrEnum):
    """Who performs a step: a person, Claude through a skill, or the platform's own code."""

    HUMAN = "human"
    AGENT = "agent"
    SCRIPT = "script"


class RefKind(StrEnum):
    SKILL = "skill"
    TOOL = "tool"
    CLI = "cli"
    PAGE = "page"


@dataclass(frozen=True)
class Ref:
    """A named thing in the code. `cli` names are the command path after `factory`."""

    kind: RefKind
    name: str


def skill(name: str) -> Ref:
    return Ref(RefKind.SKILL, name)


def tool(name: str) -> Ref:
    return Ref(RefKind.TOOL, name)


def cli(name: str) -> Ref:
    return Ref(RefKind.CLI, name)


def page(name: str) -> Ref:
    return Ref(RefKind.PAGE, name)


@dataclass(frozen=True)
class Step:
    """One act of a stage, in order. `refs` are the skills, tools, commands or pages it uses."""

    actor: Actor
    text: str
    refs: tuple[Ref, ...] = ()


@dataclass(frozen=True)
class Done:
    """When the stage is finished, as a condition a command or a page can show."""

    condition: str
    shown_by: tuple[Ref, ...]


@dataclass(frozen=True)
class StageCard:
    """One stage of a project. `id` is a lifecycle stage id of `services/site_catalog.py`."""

    id: str
    title: str
    goal: str
    acts: tuple[Actor, ...]
    gates: tuple[str, ...]
    steps: tuple[Step, ...]
    page: Ref
    done: Done
    mistakes: tuple[str, ...]
    rigour: tuple[str, ...]
    next_id: str | None


@dataclass(frozen=True)
class Concept:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class Term:
    term: str
    meaning: str

"""Create a project from the portal (plan 2026-11-13-main-hub, setup part; the first form only).

The act is the CLI's `factory init` made from a form: the same authorisation (`cli:init`), the same
`init_project` (which records `project.created` as the local human), plus the title in the portal's
`registry.json`. It never acts as the system or an agent: the only event it can write is
`project.created`, and that is the human actor's by construction.

Invariants:
- Validation comes first and a refusal writes nothing: not a folder, not an event, not a registry
  entry. The slug is checked by the same rule as the CLI (`slug_issues`, an existing project is
  refused); the profile is a rigor mode; the title is at most `MAX_TITLE` characters with no
  control characters (empty means the slug is shown).
- The title lives only in `registry.json`, which holds no research data. The file is rewritten
  atomically, keeping every other key and entry. A registry that does not parse is never
  overwritten (a hand-edited file is the researcher's): the project is created and `title_saved` is
  False.
- No model is called and no other setup form lives here (protocol, seeds, question are later).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Final

from factory.clock import Clock
from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.project import RigorMode
from factory.services.cli_access import authorise_root_command
from factory.services.context import slug_issues
from factory.services.project import init_project
from factory.services.site_portal import REGISTRY

MAX_TITLE: Final = 120
_REGISTRY_LOCK: Final = threading.Lock()


class Created(StrictModel):
    slug: str
    title: str
    profile: str
    title_saved: bool
    """False when a title was given but could not be stored (the registry does not parse)."""


def _issues(slug: object, title: object, profile: object) -> list[ValidationIssue]:
    found: list[ValidationIssue] = []
    if not isinstance(slug, str):
        found.append(ValidationIssue("slug", "must be a string"))
    else:
        found += slug_issues(slug)
    if not isinstance(title, str):
        found.append(ValidationIssue("title", "must be a string"))
    elif len(title.strip()) > MAX_TITLE:
        found.append(ValidationIssue("title", f"must be at most {MAX_TITLE} characters"))
    elif any(ord(c) < 32 or ord(c) == 127 for c in title):
        found.append(ValidationIssue("title", "must not contain control characters"))
    if not isinstance(profile, str) or profile not in {m.value for m in RigorMode}:
        choices = ", ".join(m.value for m in RigorMode)
        found.append(ValidationIssue("profile", f"must be one of: {choices}"))
    return found


def _save_title(root: Path, slug: str, title: str) -> bool:
    """Put `title` under `slug` in the registry; False when the file does not parse (left as is)."""
    path = root / REGISTRY
    with _REGISTRY_LOCK:
        data: dict[str, object] = {}
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raw = None
        except OSError:
            return False
        if raw is not None:
            try:
                loaded = json.loads(raw)
            except ValueError:
                return False
            if not isinstance(loaded, dict):
                return False
            data = loaded
        projects = data.get("projects", {})
        if not isinstance(projects, dict):
            return False
        data["projects"] = {**projects, slug: {"title": title}}
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            return False
        return True


def create_project(
    settings: Settings,
    slug: object,
    title: object,
    profile: object,
    *,
    session: str,
    clock: Clock,
) -> Created:
    """Create the project as the local human; raises `FactoryValidationError` (nothing written)
    for a bad slug, title or profile or an existing project."""
    issues = _issues(slug, title, profile)
    if issues:
        raise FactoryValidationError(issues)
    assert isinstance(slug, str) and isinstance(title, str) and isinstance(profile, str)
    authorise_root_command(settings, "cli:init", session=session, clock=clock)
    init_project(settings, slug, profile, session=session, clock=clock)
    text = title.strip()
    saved = _save_title(settings.root, slug, text) if text else True
    return Created(slug=slug, title=text or slug, profile=profile, title_saved=saved)

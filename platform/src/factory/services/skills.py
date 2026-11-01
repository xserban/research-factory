"""Skill references: the platform computes each one from the installed skill file.

A skill reference is `name@<first 8 hex of sha256(SKILL.md bytes)>`. Agents pass a bare name, or
a reference they read earlier; either way the platform answers with the reference of the file
that is installed now. A supplied hash that no longer matches is refused, so an event never
records a skill text other than the one that was installed when it was written.
"""

import hashlib
import re

from factory.config import Settings
from factory.errors import FactoryValidationError, ValidationIssue

SKILL_NAME_RE = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_HASH_RE = r"[0-9a-f]{8}"


def skill_ref(settings: Settings, skill: str) -> str:
    """The `name@hash` reference for an installed skill, checking any hash the caller supplied."""
    name, sep, given = skill.partition("@")
    if re.fullmatch(SKILL_NAME_RE, name) is None or (sep and re.fullmatch(_HASH_RE, given) is None):
        raise FactoryValidationError(
            [ValidationIssue("skill", "must be a skill name like rf-probe")]
        )
    path = settings.plugin_dir / "skills" / name / "SKILL.md"
    if not path.is_file():
        raise FactoryValidationError(
            [ValidationIssue("skill", f"no installed skill {name!r} under {settings.plugin_dir}")]
        )
    ref = f"{name}@{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"
    if sep and given != ref.partition("@")[2]:
        raise FactoryValidationError(
            [ValidationIssue("skill", f"skill file changed: installed {ref}, caller sent {skill}")]
        )
    return ref

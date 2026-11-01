"""The plugin skills resolve through the platform and carry the frontmatter the plugin requires."""

from pathlib import Path

import pytest

from factory.config import Settings
from factory.services.skills import skill_ref

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("rf-frame", "rf-probe", "rf-protocol", "rf-screen")


def _frontmatter(name: str) -> dict[str, str]:
    lines = (REPO_ROOT / "plugin" / "skills" / name / "SKILL.md").read_text("utf-8").splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(": ")
        assert sep, f"frontmatter line without key: {line!r}"
        fields[key] = value
    return fields


@pytest.mark.parametrize("name", SKILLS)
def test_plugin_skills_resolve_and_have_frontmatter(name: str) -> None:
    s = Settings.load(root=REPO_ROOT, user="obd")  # plugin_dir defaults to <repo>/plugin
    assert skill_ref(s, name).startswith(f"{name}@")
    assert _frontmatter(name)["name"] == name
    assert _frontmatter(name)["description"].startswith("Use when")

import getpass
import os
import re
from pathlib import Path
from typing import Self

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE


class Settings(StrictModel):
    """Where the factory lives, which plugin installs its skills, and who is acting.

    Built from arguments, then env, then defaults. `plugin_dir` holds `skills/<name>/SKILL.md`
    and is `plugin_override` when one was given, else `root / "plugin"`.
    """

    root: Path
    user: str
    mailto: str | None = None
    plugin_override: Path | None = None

    @property
    def plugin_dir(self) -> Path:
        return self.plugin_override or self.root / "plugin"

    @classmethod
    def load(
        cls,
        root: Path | None = None,
        user: str | None = None,
        mailto: str | None = None,
        plugin_dir: Path | None = None,
    ) -> Self:
        if root is None:
            env_root = os.environ.get("FACTORY_ROOT")
            root = Path(env_root) if env_root else Path.cwd()
        if user is None:
            user = os.environ.get("FACTORY_USER") or getpass.getuser()
        if re.fullmatch(ACTOR_ID_RE, user) is None:
            raise FactoryValidationError(
                [ValidationIssue("user", f"must match {ACTOR_ID_RE}, got {user!r}")]
            )
        if mailto is None:
            mailto = os.environ.get("FACTORY_MAILTO")
        if plugin_dir is None:
            env_plugin = os.environ.get("FACTORY_PLUGIN_DIR")
            plugin_dir = Path(env_plugin) if env_plugin else None
        return cls(root=root, user=user, mailto=mailto or None, plugin_override=plugin_dir)

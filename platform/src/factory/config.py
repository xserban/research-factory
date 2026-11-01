import getpass
import os
import re
from pathlib import Path
from typing import Self

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE


class Settings(StrictModel):
    """Where the factory lives and who is acting. Built from arguments, then env, then defaults."""

    root: Path
    user: str
    mailto: str | None = None

    @classmethod
    def load(
        cls,
        root: Path | None = None,
        user: str | None = None,
        mailto: str | None = None,
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
        return cls(root=root, user=user, mailto=mailto or None)

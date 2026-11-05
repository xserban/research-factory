import getpass
import os
import re
from pathlib import Path
from typing import Self

from pydantic import Field

from factory.errors import FactoryValidationError, ValidationIssue
from factory.model.base import StrictModel
from factory.model.identity import ACTOR_ID_RE

DEFAULT_VOCAB = "https://w3id.org/research-factory/vocab#"
"""A placeholder namespace until the researcher registers one (plan X-B, ruling 4)."""


class Settings(StrictModel):
    """Where the factory lives, which plugin installs its skills, and who is acting.

    Built from arguments, then env, then defaults. `plugin_dir` holds `skills/<name>/SKILL.md`
    and is `plugin_override` when one was given, else `root / "plugin"`. `host_id` names this
    machine as a host of projects (slice 5 ruling 2): from the argument, `FACTORY_HOST_ID` or
    `<root>/.server/host_id`; None on a personal machine. `orcid`, `licence` and `vocab` name the
    researcher, the project's licence and the RDF vocabulary in exports (plan X-B); they come from
    the environment and the export that uses them checks them.
    """

    root: Path
    user: str
    mailto: str | None = None
    plugin_override: Path | None = None
    host_id: str | None = Field(default=None, pattern=ACTOR_ID_RE)
    orcid: str | None = None
    licence: str | None = None
    vocab: str = DEFAULT_VOCAB

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
        host_id: str | None = None,
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
        host_id = host_id or os.environ.get("FACTORY_HOST_ID") or _stored_host_id(root)
        if host_id is not None and re.fullmatch(ACTOR_ID_RE, host_id) is None:
            raise FactoryValidationError(
                [ValidationIssue("host_id", f"must match {ACTOR_ID_RE}, got {host_id!r}")]
            )
        return cls(
            root=root,
            user=user,
            mailto=mailto or None,
            plugin_override=plugin_dir,
            host_id=host_id,
            orcid=os.environ.get("FACTORY_ORCID") or None,
            licence=os.environ.get("FACTORY_LICENCE") or None,
            vocab=os.environ.get("FACTORY_VOCAB") or DEFAULT_VOCAB,
        )


def _stored_host_id(root: Path) -> str | None:
    path = root / ".server" / "host_id"
    return (path.read_text().strip() or None) if path.is_file() else None

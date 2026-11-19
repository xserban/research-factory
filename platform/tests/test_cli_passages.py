"""CLI `factory passages` (IDEA-102): embed and status, with a fake embedder (no weights)."""

# ruff: noqa: F811
import pytest

from factory.cli.main import app
from factory.config import Settings
from factory.services import passage_vectors as pv
from factory.services.context import Project
from factory.services.ranking_model import ranker_unavailable
from tests.cli_helpers import _env, runner
from tests.extraction_helpers import screened  # noqa: F401
from tests.test_corpus_search import _convert
from tests.test_passage_vectors import FakeEmbedder


def test_status_embed_status(
    settings: Settings, project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _convert(project)
    monkeypatch.setattr(pv, "default_embedder", lambda: FakeEmbedder())
    total = 3 * len(screened)
    key = pv.model_key(FakeEmbedder())
    before = runner.invoke(app, ["passages", "status"], env=_env(settings.root))
    assert before.exit_code == 0, before.stderr
    assert before.stdout.strip() == f"passages {total}, embedded 0, missing {total}; key {key}"
    embed = runner.invoke(app, ["passages", "embed"], env=_env(settings.root))
    assert embed.exit_code == 0, embed.stderr
    lines = embed.stdout.splitlines()
    assert f"embedded {total}/{total}" in lines
    assert lines[-1].startswith(f"embedded {total}, already held 0, removed 0, missing 0")
    again = runner.invoke(app, ["passages", "embed"], env=_env(settings.root))
    assert again.stdout.splitlines()[-1].startswith(f"embedded 0, already held {total}")
    after = runner.invoke(app, ["passages", "status"], env=_env(settings.root))
    assert after.stdout.strip() == f"passages {total}, embedded {total}, missing 0; key {key}"


def test_embed_without_model_refuses(
    settings: Settings, project: Project, screened: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> FakeEmbedder:
        raise ranker_unavailable("FACTORY_RANKER_MODEL is not set")

    monkeypatch.setattr(pv, "default_embedder", unavailable)
    result = runner.invoke(app, ["passages", "embed"], env=_env(settings.root))
    assert result.exit_code == 1
    assert "ranker:" in result.stderr

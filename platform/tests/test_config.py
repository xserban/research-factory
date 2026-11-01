import getpass
from pathlib import Path

import pytest

from factory.config import Settings
from factory.errors import FactoryValidationError


def test_settings_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FACTORY_ROOT", str(tmp_path / "env"))
    monkeypatch.setenv("FACTORY_USER", "envuser")
    assert Settings.load().root == tmp_path / "env"
    assert Settings.load().user == "envuser"
    assert Settings.load(root=tmp_path, user="obd") == Settings(root=tmp_path, user="obd")


def test_settings_defaults_to_cwd_and_os_user(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("FACTORY_ROOT", raising=False)
    monkeypatch.delenv("FACTORY_USER", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings.load()
    assert settings.root == Path.cwd()
    assert settings.user == getpass.getuser()


def test_invalid_user_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FactoryValidationError) as err:
        Settings.load(root=tmp_path, user="Not A User")
    assert [issue.field for issue in err.value.issues] == ["user"]


def test_mailto_defaults_to_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FACTORY_MAILTO", raising=False)
    assert Settings.load(root=tmp_path, user="obd").mailto is None


def test_settings_reads_mailto_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FACTORY_MAILTO", "someone@example.org")
    assert Settings.load(root=tmp_path, user="obd").mailto == "someone@example.org"
    assert Settings.load(root=tmp_path, user="obd", mailto="other@example.org").mailto == (
        "other@example.org"
    )


def test_empty_mailto_env_means_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FACTORY_MAILTO", "")
    assert Settings.load(root=tmp_path, user="obd").mailto is None
